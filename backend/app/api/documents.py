"""
文档管理 API - 支持进度条上传和智能分块
"""
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException

from app.services.document_service import DocumentService, UPLOAD_DIR
from app.services.document_parser import DocumentParser
from app.services.knowledge_graph import kg_service
from app.core.chunking import ChunkingService
from app.core.recycle_bin import get_recycle_bin
from app.core.vector_store import VectorStore

router = APIRouter()
document_service = DocumentService()

# 全局进度存储
_upload_progress: dict[str, dict] = {}

# 文档迁移操作日志（任务 4.3 / 任务 P0-2: SQLite 迁移）
# 路径：基于当前文件位置（backend/app/api/documents.py）的上层 data 目录
_OP_LOG_FILE = Path(__file__).resolve().parents[2] / "data" / "op_log.json"
_OP_LOG: List[dict] = []


def _load_op_log():
    """任务 P0-2: 优先 SQLite，fallback JSON"""
    global _OP_LOG
    # 优先 SQLite
    try:
        from app.core.db import get_db_session
        from app.core.models import OpLog
        from datetime import datetime
        with get_db_session() as session:
            rows = session.query(OpLog).order_by(OpLog.time.asc()).limit(500).all()
            _OP_LOG = []
            for r in rows:
                entry = {
                    "time": r.time.isoformat() if r.time else "",
                    "operator": r.operator or "",
                    "action": r.action or "",
                    "doc_ids": list(r.doc_ids or []),
                    "target": r.target or "",
                    "migrated_count": r.migrated_count or 0,
                    "skipped_count": r.skipped_count or 0,
                    "chunks_updated": r.chunks_updated or 0,
                }
                if r.extra:
                    entry.update(r.extra)
                _OP_LOG.append(entry)
        if _OP_LOG:
            return
    except Exception as e:
        print(f"[_load_op_log] SQLite failed, fallback JSON: {e}")
    # Fallback: JSON
    if _OP_LOG_FILE.exists():
        try:
            with open(_OP_LOG_FILE, "r", encoding="utf-8") as f:
                _OP_LOG = json.load(f) or []
        except Exception:
            _OP_LOG = []


def _save_op_log():
    """任务 P0-2: 优先 SQLite（追加），fallback JSON"""
    # 优先 SQLite（追加新条目，不删历史）
    try:
        from app.core.db import get_db_session
        from app.core.models import OpLog
        from datetime import datetime
        with get_db_session() as session:
            for entry in _OP_LOG[-10:]:  # 只写最新 10 条（避免重复写）
                t = entry.get("time")
                dt = None
                if isinstance(t, str):
                    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
                        try:
                            dt = datetime.strptime(t, fmt)
                            break
                        except ValueError:
                            continue
                # 避免重复（检查最近是否有同 operator + action + time）
                existing = session.query(OpLog).filter_by(
                    operator=entry.get("operator", ""),
                    action=entry.get("action", ""),
                    time=dt,
                ).first()
                if existing:
                    continue
                standard_fields = {"time", "operator", "action", "doc_ids", "target", "migrated_count", "skipped_count", "chunks_updated"}
                session.add(OpLog(
                    time=dt or datetime.now(),
                    operator=entry.get("operator", ""),
                    action=entry.get("action", ""),
                    doc_ids=entry.get("doc_ids", []),
                    target=entry.get("target", ""),
                    migrated_count=entry.get("migrated_count", 0),
                    skipped_count=entry.get("skipped_count", 0),
                    chunks_updated=entry.get("chunks_updated", 0),
                    extra={k: v for k, v in entry.items() if k not in standard_fields},
                ))
        return
    except Exception as e:
        print(f"[_save_op_log] SQLite failed, fallback JSON: {e}")
    # Fallback: JSON
    try:
        _OP_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_OP_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(_OP_LOG[-500:], f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存操作日志失败: {e}")


_load_op_log()


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(None),
    category: str = Form("默认"),
    strategy: str = Form("auto"),
    knowledge_base_id: str = Form("default")
):
    """上传文档，自动推荐分块策略"""
    import uuid
    task_id = str(uuid.uuid4())
    
    # 先读取文件内容（只能读一次）
    file_content = await file.read()
    file_name = file.filename
    
    async def process_with_progress():
        try:
            # 阶段 1: 解析文档 (10%)
            _upload_progress[task_id] = {"progress": 5, "status": "正在解析文档...", "done": False}
            await asyncio.sleep(0.1)
            
            content = DocumentParser.parse_bytes(file_content, file_name)
            _upload_progress[task_id]["progress"] = 10
            
            # 阶段 2: 智能推荐分块策略 (20%)
            _upload_progress[task_id]["status"] = "正在分析文档结构..."
            
            recommended_strategy = None
            if strategy == "auto":
                recommended = ChunkingService.recommend_strategy(content, title or file_name)
                recommended_strategy = recommended.get("recommended_strategy", "recursive")
                _upload_progress[task_id]["recommended_strategy"] = recommended_strategy
                _upload_progress[task_id]["recommendation_reason"] = recommended.get("reason", "")
            else:
                recommended_strategy = strategy
            
            _upload_progress[task_id]["progress"] = 20
            
            # 阶段 3: 分块处理 (50%)
            _upload_progress[task_id]["status"] = f"正在使用 {recommended_strategy} 策略分块..."
            
            chunks = ChunkingService.chunk_text(content, category=category, strategy=recommended_strategy)
            _upload_progress[task_id]["chunk_count"] = len(chunks)
            _upload_progress[task_id]["progress"] = 50
            
            # 阶段 4: 保存文档 (60%)
            _upload_progress[task_id]["status"] = "正在保存文档..."
            doc = document_service.save_document_sync(file_name, file_content, content, title, category, knowledge_base_id=knowledge_base_id)
            _upload_progress[task_id]["progress"] = 60
            
            # 阶段 5: 向量索引 (80%)
            _upload_progress[task_id]["status"] = "正在构建向量索引..."
            if chunks:
                metadata = [{
                    "doc_id": doc.id,
                    "title": doc.title,
                    "category": category,
                    "knowledge_base_id": knowledge_base_id,
                    "chunk_index": i,
                    "strategy": recommended_strategy
                } for i in range(len(chunks))]
                VectorStore.add_document(doc.id, chunks, metadata)
            
            _upload_progress[task_id]["progress"] = 80
            
            # 阶段 6: 构建知识图谱 (100%)
            _upload_progress[task_id]["status"] = "正在构建知识图谱..."
            from app.services.knowledge_graph import KnowledgeGraphService
            kb_graph = KnowledgeGraphService(knowledge_base_id=knowledge_base_id)
            result = kb_graph.build_from_document(doc.id, doc.title, content)
            
            _upload_progress[task_id]["progress"] = 100
            _upload_progress[task_id]["status"] = "完成"
            _upload_progress[task_id]["done"] = True
            _upload_progress[task_id]["doc_id"] = doc.id
            _upload_progress[task_id]["graph_result"] = result
            
        except Exception as e:
            import traceback
            _upload_progress[task_id]["status"] = f"错误: {str(e)}"
            _upload_progress[task_id]["done"] = True
            _upload_progress[task_id]["error"] = str(e)
            _upload_progress[task_id]["traceback"] = traceback.format_exc()
    
    asyncio.create_task(process_with_progress())
    return {"task_id": task_id, "message": "上传任务已启动"}


@router.get("/progress/{task_id}")
async def get_progress(task_id: str):
    """获取上传进度"""
    progress = _upload_progress.get(task_id, {"progress": 0, "status": "未知任务", "done": False})
    return progress


@router.get("/migration-log")
async def get_migration_log(limit: int = 50):
    """获取文档迁移操作日志（最新在前）"""
    return list(reversed(_OP_LOG[-limit:]))


# ==================== 任务 1：知识库元数据端点（无需 RAG 检索） ====================
@router.get("/meta-summary")
async def get_meta_summary(category: str = None):
    """返回知识库元数据全貌（文档清单 + 分类清单 + 统计数字）

    任务 1：用于支持"现在知识库有哪些内容"等元数据级查询，绕过 RAG 检索。
    """
    docs = document_service.get_documents(category)
    # 按分类聚合
    by_category: dict[str, list[dict]] = {}
    for d in docs:
        by_category.setdefault(d.category, []).append({
            "id": d.id,
            "title": d.title,
            "file_type": d.file_type,
            "owner": d.owner,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        })
    return {
        "total_documents": len(docs),
        "total_categories": len(by_category),
        "total_chunks": VectorStore.count_total(),
        "categories": [
            {
                "name": cat,
                "count": len(items),
                "documents": items,
            }
            for cat, items in sorted(by_category.items(), key=lambda x: -len(x[1]))
        ],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


@router.get("/list")
async def list_documents(category: str = None, knowledge_base_id: str = "all"):
    """获取文档列表（任务 2：按 KB 过滤）"""
    import traceback
    try:
        docs = document_service.get_documents(category)
        # KB 过滤
        if knowledge_base_id != "all":
            docs = [d for d in docs if getattr(d, "knowledge_base_id", "default") == knowledge_base_id]
        # 只返回摘要信息，避免 content 过大导致序列化问题
        result = []
        for d in docs:
            result.append({
                "id": d.id,
                "title": d.title,
                "category": d.category,
                "knowledge_base_id": getattr(d, "knowledge_base_id", "default"),
                "file_type": d.file_type if hasattr(d, 'file_type') else "txt",
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "content_preview": d.content[:200] if d.content else "",
                "chunk_count": VectorStore.count_by_doc_id(d.id),
            })
        return result
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"list_documents error: {str(e)}")


@router.get("/{doc_id}/raw")
async def get_document_raw(doc_id: str, download: bool = False):
    """获取原始上传文件（用于预览/下载）

    返回 StreamingResponse 携带正确的 Content-Disposition 和 Content-Type，
    浏览器可直接渲染（PDF/图片）或作为下载（Office 等不支持的格式）。
    ?download=1 → 强制 attachment 下载；否则 inline 内联预览。
    """
    from fastapi.responses import FileResponse
    doc = document_service.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"文档 {doc_id} 不存在")

    # 优先用 doc.filename 重建文件路径；否则扫描 UPLOAD_DIR
    filename = getattr(doc, 'filename', None) or doc.title
    file_path = UPLOAD_DIR / f"{doc_id}_{filename}"
    if not file_path.exists():
        # 退化方案：扫描以 doc_id 开头的文件
        matches = list(UPLOAD_DIR.glob(f"{doc_id}_*"))
        if not matches:
            raise HTTPException(status_code=404, detail=f"原始文件不存在：{filename}")
        file_path = matches[0]
        filename = file_path.name[len(doc_id) + 1:]  # 去掉 "{doc_id}_" 前缀

    # 按扩展名映射 MIME
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    mime_map = {
        'pdf': 'application/pdf',
        'txt': 'text/plain; charset=utf-8',
        'md': 'text/markdown; charset=utf-8',
        'markdown': 'text/markdown; charset=utf-8',
        'html': 'text/html; charset=utf-8',
        'htm': 'text/html; charset=utf-8',
        'json': 'application/json; charset=utf-8',
        'csv': 'text/csv; charset=utf-8',
        'png': 'image/png',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'gif': 'image/gif',
        'webp': 'image/webp',
        'svg': 'image/svg+xml',
    }
    media_type = mime_map.get(ext, 'application/octet-stream')
    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=filename,
        content_disposition_type='attachment' if download else 'inline',
    )


@router.get("/{doc_id}")
async def get_document(doc_id: str):
    """获取单个文档"""
    return document_service.get_document(doc_id)


@router.delete("/{doc_id}")
async def delete_document(doc_id: str, soft: bool = True):
    """删除文档

    软删除（默认 soft=True）：放入回收站 + 级联删除图谱关联 + 7 天可恢复
    硬删除（soft=False）：立即清空向量库 + 文档 + 图谱
    """
    # 先查文档元数据（用于回收站备份）
    doc = document_service.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"文档 {doc_id} 不存在")

    cascade_info = {}

    if soft:
        # 1. 备份到回收站（含内容前 10K 用于恢复时重建图谱）
        content = getattr(doc, 'content', '') or ''
        get_recycle_bin().put(
            doc_id=doc_id,
            doc_data={
                "id": doc.id,
                "title": doc.title,
                "category": doc.category,
                "file_type": doc.file_type,
                "created_at": doc.created_at,
            },
            content=content,
        )
        # 2. 删除向量
        VectorStore.delete_document(doc_id)
        # 3. 级联删除图谱节点
        try:
            cascade_info = kg_service.delete_by_doc_id(doc_id)
        except Exception as e:
            logger.warning(f"[文档删除] 图谱级联删除失败（已忽略）: {e}")
        # 4. 删除文档元数据
        document_service.delete_document(doc_id)
        return {
            "message": "moved_to_recycle",
            "doc_id": doc_id,
            "recycle_retention_days": 7,
            "cascade": cascade_info,
        }
    else:
        # 硬删除
        VectorStore.delete_document(doc_id)
        try:
            cascade_info = kg_service.delete_by_doc_id(doc_id)
        except Exception as e:
            logger.warning(f"[文档删除] 图谱级联删除失败（已忽略）: {e}")
        document_service.delete_document(doc_id)
        return {"message": "deleted", "doc_id": doc_id, "cascade": cascade_info}


@router.post("/recycle/list")
async def list_recycle():
    """列出回收站中的文档"""
    items = get_recycle_bin().list()
    return {
        "success": True,
        "items": [
            {
                "doc_id": it["doc_id"],
                "title": it["doc_data"].get("title", ""),
                "category": it["doc_data"].get("category", ""),
                "deleted_at": it["deleted_at"],
                "expires_at": it["expires_at"],
                "remaining_days": max(0, (it["expires_at"] - time.time()) / 86400),
            }
            for it in items
        ],
    }


@router.post("/recycle/restore")
async def restore_from_recycle(doc_id: str):
    """从回收站恢复文档

    1. 取出备份数据
    2. 重新添加到文档服务
    3. 重新向量化入库
    4. 重建图谱关联
    """
    import time
    item = get_recycle_bin().pop(doc_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"回收站中无此文档 {doc_id}")

    doc_data = item["doc_data"]
    content = item.get("content", "")

    # 1. 恢复文档元数据
    new_doc = document_service.save_document_sync(
        filename=doc_data.get("title", doc_id),
        file_content=b"",
        parsed_content=content,
        title=doc_data.get("title"),
        category=doc_data.get("category", "默认"),
    )

    # 2. 重建图谱
    cascade_info = {}
    try:
        result = kg_service.build_from_document(
            doc_id=new_doc.id,
            title=doc_data.get("title", ""),
            content=content[:5000],
        )
        cascade_info = {
            "nodes_added": result.get("nodes_added", 0),
            "edges_added": result.get("edges_added", 0),
        }
    except Exception as e:
        logger.warning(f"[恢复] 重建图谱失败: {e}")

    return {
        "success": True,
        "doc_id": new_doc.id,
        "title": new_doc.title,
        "graph_rebuilt": cascade_info,
    }


@router.delete("/recycle/{doc_id}")
async def hard_delete_from_recycle(doc_id: str):
    """从回收站永久删除（必须级联清理向量库 + 图谱）"""
    item = get_recycle_bin().pop(doc_id)
    if not item:
        return {"success": False, "error": "回收站中无此文档"}
    cascade_info = {}
    # 修复：硬删除时必须清理向量库与图谱节点，避免幽灵残留
    try:
        VectorStore.delete_document(doc_id)
    except Exception as e:
        logger.warning(f"[回收站硬删除] 向量清理失败（已忽略）: {e}")
    try:
        cascade_info = kg_service.delete_by_doc_id(doc_id)
    except Exception as e:
        logger.warning(f"[回收站硬删除] 图谱清理失败（已忽略）: {e}")
    return {"success": True, "doc_id": doc_id, "cascade": cascade_info}


@router.post("/recycle/cleanup")
async def cleanup_recycle():
    """清理回收站过期项（>7天）"""
    removed = get_recycle_bin().cleanup_expired()
    return {"success": True, "removed": removed}


@router.put("/{doc_id}/category")
async def update_document_category(doc_id: str, category: str, operator: str = "system"):
    """更新文档的分类（同步向量库元数据 + 记录操作日志）"""
    if not document_service.get_document(doc_id):
        raise HTTPException(status_code=404, detail=f"文档 {doc_id} 不存在")
    old_category = document_service.get_document(doc_id).category
    document_service.update_document_category(doc_id, category)
    # 同步更新向量库检索元数据
    chunks_updated = VectorStore.update_category(doc_id, category)
    # 记录操作日志
    _OP_LOG.append({
        "time": datetime.now().isoformat(timespec="seconds"),
        "operator": operator,
        "action": "migrate_single",
        "doc_ids": [doc_id],
        "from": old_category,
        "to": category,
        "chunks_updated": chunks_updated,
    })
    _save_op_log()
    return {"message": "updated", "doc_id": doc_id, "category": category, "chunks_updated": chunks_updated}


@router.post("/migrate-batch")
async def migrate_documents_batch(payload: dict, operator: str = "system"):
    """批量迁移文档至新分类

    Payload: { doc_ids: [..], target_category: str }
    同步更新向量库元数据 + 记录操作日志
    """
    doc_ids = payload.get("doc_ids", [])
    target = payload.get("target_category", "").strip()
    if not doc_ids or not target:
        raise HTTPException(status_code=400, detail="doc_ids 与 target_category 必填")
    migrated = []
    skipped = []
    total_chunks = 0
    for did in doc_ids:
        doc = document_service.get_document(did)
        if not doc:
            skipped.append({"doc_id": did, "reason": "not_found"})
            continue
        old_category = doc.category
        document_service.update_document_category(did, target)
        chunks = VectorStore.update_category(did, target)
        total_chunks += chunks
        migrated.append({
            "doc_id": did,
            "title": doc.title,
            "from": old_category,
            "to": target,
            "chunks_updated": chunks,
        })
    _OP_LOG.append({
        "time": datetime.now().isoformat(timespec="seconds"),
        "operator": operator,
        "action": "migrate_batch",
        "doc_ids": doc_ids,
        "target": target,
        "migrated_count": len(migrated),
        "skipped_count": len(skipped),
        "chunks_updated": total_chunks,
    })
    _save_op_log()
    return {
        "success": True,
        "migrated": migrated,
        "skipped": skipped,
        "total_chunks_updated": total_chunks,
    }


@router.post("/migrate-batch-stream")
async def migrate_documents_batch_stream(payload: dict, operator: str = "system"):
    """任务 2.2：批量迁移 + SSE 流式进度

    Payload: { doc_ids: [..], target_category: str, owner: str | None }
    逐文件处理，每个 doc 完成/失败都发 SSE 事件：
    - {"type":"start","total":N,"index":0,"doc_id":"..."}
    - {"type":"done","index":0,"doc_id":"...","ok":true,"chunks_updated":55}
    - {"type":"error","index":1,"doc_id":"...","error":"..."}
    - {"type":"summary","ok_count":8,"fail_count":1,"total_chunks":200}
    """
    from fastapi.responses import StreamingResponse
    import json as _json

    doc_ids = payload.get("doc_ids", [])
    target = payload.get("target_category", "").strip()
    owner = payload.get("owner")  # 透传所有者（任务 2.1）
    if not doc_ids or not target:
        raise HTTPException(status_code=400, detail="doc_ids 与 target_category 必填")

    def _sse(event: dict) -> str:
        return f"data: {_json.dumps(event, ensure_ascii=False)}\n\n"

    def _gen():
        ok_count = 0
        fail_count = 0
        failed_ids: list[str] = []
        total_chunks = 0
        for i, did in enumerate(doc_ids):
            yield _sse({"type": "start", "index": i, "total": len(doc_ids), "doc_id": did})
            try:
                doc = document_service.get_document(did)
                if not doc:
                    fail_count += 1
                    failed_ids.append(did)
                    yield _sse({
                        "type": "error", "index": i, "doc_id": did,
                        "error": "document not found",
                    })
                    continue
                old_category = doc.category
                # 透传 owner（任务 2.1）
                if owner is not None and getattr(doc, "owner", None) != owner:
                    doc.owner = owner
                document_service.update_document_category(did, target)
                chunks = VectorStore.update_category(did, target)
                total_chunks += chunks
                ok_count += 1
                yield _sse({
                    "type": "done", "index": i, "doc_id": did,
                    "title": doc.title,
                    "from": old_category, "to": target,
                    "chunks_updated": chunks,
                    "ok": True,
                })
            except Exception as e:
                fail_count += 1
                failed_ids.append(did)
                yield _sse({
                    "type": "error", "index": i, "doc_id": did,
                    "error": str(e),
                })

        _OP_LOG.append({
            "time": datetime.now().isoformat(timespec="seconds"),
            "operator": operator,
            "action": "migrate_batch_stream",
            "doc_ids": doc_ids,
            "target": target,
            "owner": owner,
            "ok_count": ok_count,
            "fail_count": fail_count,
            "chunks_updated": total_chunks,
        })
        _save_op_log()
        yield _sse({
            "type": "summary",
            "total": len(doc_ids),
            "ok_count": ok_count,
            "fail_count": fail_count,
            "failed_ids": failed_ids,
            "total_chunks_updated": total_chunks,
        })
        yield "data: {\"type\":\"done\"}\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")


@router.get("/{doc_id}/chunk/{chunk_id}")
async def get_chunk_content(doc_id: str, chunk_id: str):
    """获取文档某个分块的原文（用于溯源跳转）

    Args:
        doc_id: 文档 ID
        chunk_id: 分块 ID（向量库中的 id），格式: "{doc_id}_chunk_{index}"
    """
    # 从向量库取出该分块
    all_chunks = VectorStore.list_chunks_by_doc(doc_id)
    chunk = next((c for c in all_chunks if c["id"] == chunk_id), None)
    if not chunk:
        raise HTTPException(status_code=404, detail=f"分块 {chunk_id} 不存在")
    return {
        "doc_id": doc_id,
        "chunk_id": chunk_id,
        "content": chunk["content"],
        "metadata": chunk["metadata"],
    }


@router.get("/stats/vector")
async def vector_stats():
    """获取向量库统计"""
    return VectorStore.get_stats()


@router.get("/stats/dashboard")
async def dashboard_stats():
    """获取工作台仪表盘统计"""
    import json
    from pathlib import Path

    # 1. 文档统计
    docs = document_service.get_documents()
    doc_count = len(docs)

    # 2. 向量库统计
    vec_stats = VectorStore.get_stats()

    # 3. 分类统计
    from collections import Counter
    categories = Counter(getattr(d, "category", "默认") for d in docs)

    # 5. 聊天会话统计（任务 P0-2: 优先 SQLite，fallback JSON）
    chat_sessions = 0
    chat_messages = 0
    try:
        from app.core.db import get_db_session
        from app.core.models import ChatStat
        with get_db_session() as session:
            row = session.query(ChatStat).filter_by(id=1).first()
            if row:
                chat_sessions = row.total_sessions or 0
                chat_messages = row.total_messages or 0
            else:
                raise ValueError("no chat_stats row")
    except Exception:
        # Fallback: JSON
        chat_stats_path = Path("data/chat_stats.json")
        if chat_stats_path.exists():
            try:
                stats_data = json.loads(chat_stats_path.read_text(encoding="utf-8"))
                chat_sessions = stats_data.get("total_sessions", 0)
                chat_messages = stats_data.get("total_messages", 0)
            except Exception:
                pass

    # 6. 热门提问（从热门问题快照读取）
    hot_questions = []
    hot_path = Path("data/hot_questions.json")
    if hot_path.exists():
        try:
            hot_questions = json.loads(hot_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    if not hot_questions:
        hot_questions = [
            {"question": "暂无数据", "count": 0, "trend": "stable"}
        ]

    return {
        "documents": {
            "total": doc_count,
            "categories": dict(categories),
        },
        "vector_store": vec_stats,
        "qa_stats": {
            "total_sessions": chat_sessions,
            "total_messages": chat_messages,
            "avg_messages_per_session": round(chat_messages / max(chat_sessions, 1), 1),
        },
        "knowledge_base": {
            "total": len(categories),
            "category_list": list(categories.keys()),
        },
        "hot_questions": hot_questions[:10],
        "system_status": {
            "vector_service": "normal",
            "ai_model": "normal",
            "api_server": "normal",
        }
    }


@router.post("/stats/chat/sync")
async def sync_chat_stats(stats: dict):
    """同步前端对话统计到后端持久化（任务 P0-2: 优先 SQLite，fallback JSON）"""
    import json
    from pathlib import Path

    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)

    # 优先 SQLite
    try:
        from app.core.db import get_db_session
        from app.core.models import ChatStat
        with get_db_session() as session:
            row = session.query(ChatStat).filter_by(id=1).first()
            if row:
                row.total_sessions = stats.get("total_sessions", row.total_sessions or 0)
                row.total_messages = stats.get("total_messages", row.total_messages or 0)
            else:
                session.add(ChatStat(
                    id=1,
                    total_sessions=stats.get("total_sessions", 0),
                    total_messages=stats.get("total_messages", 0),
                ))
        return {"success": True}
    except Exception as e:
        print(f"[sync_chat_stats] SQLite failed, fallback JSON: {e}")
    # Fallback: JSON
    chat_stats_path = data_dir / "chat_stats.json"
    try:
        chat_stats_path.write_text(
            json.dumps(stats, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

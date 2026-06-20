"""
向量数据库服务 - ChromaDB 适配层

任务 Z（架构升级）：从"纯 Python + JSON 持久化"升级到 ChromaDB 嵌入式
- 引入 ANN 索引（HNSW），检索性能从 O(N) 提升到 O(log N)
- 引入类型化的 metadata 过滤，分类/知识库过滤走数据库而非应用层
- 持久化目录：data/chroma/（相对路径，向后兼容）
- API 兼容性：保持 VectorStore 公开方法签名完全不变

支持开关：
- USE_CHROMA=1（默认）：使用 ChromaDB
- USE_CHROMA=0：使用原 JSON 实现（紧急回滚用）
- AUTO_MIGRATE_FROM_JSON=1（默认）：启动时自动从 vector_store.json 迁移到 Chroma

降级策略：
- ChromaDB 不可用（ImportError / 初始化失败）→ 自动回退到内嵌 JSON 实现
- 迁移失败时保留原 JSON 文件，可手动回滚
"""
import os
import json
import math
import shutil
import logging
from typing import List, Optional, Any, Dict
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

# 持久化路径
DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
# 任务 P0: 切换到 chroma_db_v2 目录（旧的 chroma/ 目录因 Windows mmap 锁无法删除，
# 但 chroma_db_v2/ 可以安全删除和重建）。这样能确保用 Qwen3-Embedding-0.6B 1024 维重建。
CHROMA_PERSIST_DIR = DATA_DIR / "chroma_db_v2"
JSON_BACKUP_PATH = DATA_DIR / "vector_store.json"

# Collection 名称（按 embedding 维度区分，避免维度不匹配冲突）
# 不同维度的 embedding 会使用不同的 collection，因为 ChromaDB 不支持修改已存在 collection 的维度
def _get_collection_name() -> str:
    """根据当前 embedding 服务的维度动态生成 collection 名。

    这样：
    - 1024 维（Qwen3-0.6B）→ chunks_d1024
    - 4096 维（Qwen3-VL-8B）→ chunks_d4096
    - 切换维度时通过 collection 名隔离，避免维度冲突异常
    """
    try:
        from app.core.embedding import get_embedding_service
        dim = get_embedding_service().dimension()
    except Exception:
        dim = 1024  # fallback
    return f"chunks_d{dim}"

COLLECTION_NAME = _get_collection_name()

# 运行时开关
USE_CHROMA = os.getenv("USE_CHROMA", "1") == "1"
AUTO_MIGRATE = os.getenv("AUTO_MIGRATE_FROM_JSON", "1") == "1"
CHROMA_BATCH = int(os.getenv("CHROMA_BATCH", "2000"))


def get_embedding_service_lazy():
    """延迟导入 embedding（避免在某些 Windows 环境下触发崩溃）"""
    from app.core.embedding import get_embedding_service
    return get_embedding_service()


# ===================================================================
# ChromaDB 懒加载
# ===================================================================
_chroma_client = None
_chroma_collection = None
_chroma_available: Optional[bool] = None  # None=未初始化, True/False=已确定


def _init_chroma():
    """初始化 Chroma PersistentClient 与 collection。失败时返回 None（不抛错）"""
    global _chroma_client, _chroma_collection, _chroma_available
    if not USE_CHROMA:
        return None
    if _chroma_collection is not None:
        return _chroma_collection
    try:
        import chromadb
        # chromadb 0.5.20 的 PersistentClient 不需要传 Settings 即可工作
        # 0.5.x 默认 backend 是 duckdb+parquet
        CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True)
        # 使用绝对路径避免 Chroma 内部相对路径解析问题
        abs_path = str(CHROMA_PERSIST_DIR.resolve())
        _chroma_client = chromadb.PersistentClient(path=abs_path)
        _chroma_collection = _chroma_client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        _chroma_available = True
        logger.info(
            f"[Chroma] 初始化完成 | dir={abs_path} | "
            f"collection={COLLECTION_NAME} | distance=cosine | count={_chroma_collection.count()}"
        )
        return _chroma_collection
    except ImportError as e:
        _chroma_available = False
        logger.error(f"[Chroma] 不可用: {e}，回退到 JSON 实现")
        return None
    except Exception as e:
        _chroma_available = False
        logger.error(f"[Chroma] 初始化失败: {e}，回退到 JSON 实现")
        return None


# ===================================================================
# 兼容性 JSON 存储（仅在 USE_CHROMA=0 或 Chroma 不可用时启用）
# ===================================================================
_legacy_data = {
    "chunks": [],
    "embeddings": [],
    "metadata": [],
    "ids": [],
}
_legacy_loaded = False


def _cosine_similarity(a: list, b: list) -> float:
    """兼容兜底：纯 Python 余弦相似度"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a)) + 1e-8
    norm_b = math.sqrt(sum(y * y for y in b)) + 1e-8
    return dot / (norm_a * norm_b)


def _load_legacy():
    """从 vector_store.json 加载到内存（兜底实现用）"""
    global _legacy_loaded
    if _legacy_loaded:
        return
    _legacy_loaded = True
    if not JSON_BACKUP_PATH.exists():
        return
    try:
        with open(JSON_BACKUP_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        _legacy_data["chunks"] = data.get("chunks", [])
        _legacy_data["embeddings"] = data.get("embeddings", [])
        _legacy_data["metadata"] = data.get("metadata", [])
        _legacy_data["ids"] = data.get("ids", [])
        dim_hint = len(_legacy_data["embeddings"][0]) if _legacy_data["embeddings"] else "N/A"
        logger.info(
            f"[VectorStore/Legacy] JSON 加载: {len(_legacy_data['chunks'])} 个分块 (dim={dim_hint})"
        )
    except Exception as e:
        logger.error(f"[VectorStore/Legacy] 加载失败: {e}")


def _save_legacy():
    """保存到 vector_store.json（兜底实现用）"""
    try:
        with open(JSON_BACKUP_PATH, "w", encoding="utf-8") as f:
            json.dump(_legacy_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"[VectorStore/Legacy] 保存失败: {e}")


# 启动期不主动初始化 Chroma 客户端：避免 ChromaDB 1.0 在 import 时 Rust panic
# 改为首次调用 VectorStore 方法时才懒加载（_init_chroma 内部已有 try/except）


# ===================================================================
# ChromaDB 元数据清洗
# ===================================================================
def _sanitize_metadata(meta: Dict[str, Any]) -> Dict[str, Any]:
    """ChromaDB metadata 字段必须是 str/int/float/bool，不能含 list/None/复杂对象。"""
    if not meta:
        return {}
    cleaned: Dict[str, Any] = {}
    for k, v in meta.items():
        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            cleaned[k] = v
        elif isinstance(v, list):
            cleaned[k] = ",".join(str(x) for x in v)
        else:
            try:
                cleaned[k] = str(v)
            except Exception:
                pass
    return cleaned


def _build_where(
    categories: Optional[List[str]] = None,
    knowledge_base_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """构造 ChromaDB where 过滤子句。多个条件用 $and 组合。"""
    conds: List[Dict[str, Any]] = []
    if categories:
        conds.append({"category": {"$in": list(categories)}})
    if knowledge_base_id and knowledge_base_id != "all":
        conds.append({"knowledge_base_id": knowledge_base_id})
    if not conds:
        return None
    if len(conds) == 1:
        return conds[0]
    return {"$and": conds}


# ===================================================================
# 数据迁移：vector_store.json -> Chroma
# ===================================================================
def migrate_json_to_chroma(force: bool = False) -> bool:
    """启动时一次性迁移：把 vector_store.json 导入 Chroma 集合。

    行为：
    1. 如果 Chroma 集合已经有数据（count > 0）且非 force → 跳过迁移
    2. 如果 JSON 文件不存在 → 跳过
    3. 迁移完成后保留 JSON 文件作为备份（命名为 .migrated.bak）

    Returns:
        True 表示执行了迁移，False 表示跳过或失败
    """
    if not USE_CHROMA or not AUTO_MIGRATE:
        return False
    col = _init_chroma()
    if col is None:
        return False
    if not JSON_BACKUP_PATH.exists():
        logger.info("[Migrate] 无 vector_store.json，跳过迁移")
        return False
    try:
        if not force and col.count() > 0:
            logger.info(f"[Migrate] Chroma 已有 {col.count()} 个分块，跳过迁移")
            return False
        with open(JSON_BACKUP_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        ids = data.get("ids", [])
        chunks = data.get("chunks", [])
        embeddings = data.get("embeddings", [])
        meta = data.get("metadata", [])
        if not ids or len(ids) != len(chunks) or len(chunks) != len(embeddings):
            logger.warning(
                f"[Migrate] 数据不一致 ids={len(ids)} chunks={len(chunks)} emb={len(embeddings)}"
            )
            return False
        # 清洗 metadata 并分批写入
        total = len(ids)
        for i in range(0, total, CHROMA_BATCH):
            j = min(i + CHROMA_BATCH, total)
            col.add(
                ids=ids[i:j],
                documents=chunks[i:j],
                embeddings=embeddings[i:j],
                metadatas=[_sanitize_metadata(m) for m in meta[i:j]],
            )
        logger.info(f"[Migrate] 完成：从 vector_store.json 导入 {total} 个分块到 Chroma")
        # 备份原 JSON（不删除，保留回滚可能）
        backup_path = JSON_BACKUP_PATH.with_suffix(".json.migrated.bak")
        if not backup_path.exists():
            shutil.copy(JSON_BACKUP_PATH, backup_path)
            logger.info(f"[Migrate] 原 JSON 备份为 {backup_path}")
        return True
    except Exception as e:
        logger.error(f"[Migrate] 失败: {e}")
        return False


class VectorStore:
    """向量数据库操作（基于 ChromaDB 1.0+ 嵌入式）

    任务 Z：API 100% 向后兼容，内部从纯 Python + JSON 升级到 ChromaDB。
    所有方法签名、返回结构、字段名称均与上一版完全一致。
    """

    # ============== 兼容兜底（ChromaDB 不可用时启用） ==============
    @staticmethod
    def _legacy_add_document(doc_id, chunks, metadata):
        _load_legacy()
        try:
            service = get_embedding_service_lazy()
            embeddings = service.encode(chunks)
            ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
            for i in range(len(chunks)):
                _legacy_data["ids"].append(ids[i])
                _legacy_data["chunks"].append(chunks[i])
                _legacy_data["embeddings"].append(list(embeddings[i]))
                _legacy_data["metadata"].append(metadata[i])
            _save_legacy()
            return len(chunks)
        except Exception as e:
            logger.error(f"[Legacy] add_document failed: {e}")
            return 0

    @staticmethod
    def _legacy_search(query, top_k, categories, knowledge_base_id):
        _load_legacy()
        if not _legacy_data["chunks"]:
            return []
        try:
            service = get_embedding_service_lazy()
            encode_func = getattr(service, "encode_query", service.encode)
            q = list(encode_func([query])[0])
            sims = [_cosine_similarity(q, e) for e in _legacy_data["embeddings"]]
            indexed = sorted(enumerate(sims), key=lambda x: x[1], reverse=True)
            cat_filter = set(categories) if categories else None
            kb_filter = knowledge_base_id if knowledge_base_id and knowledge_base_id != "all" else None
            out = []
            for idx, s in indexed[: top_k * 3]:
                m = _legacy_data["metadata"][idx]
                if cat_filter is not None and m.get("category", "默认") not in cat_filter:
                    continue
                if kb_filter is not None and m.get("knowledge_base_id", "default") != kb_filter:
                    continue
                out.append({
                    "id": _legacy_data["ids"][idx],
                    "content": _legacy_data["chunks"][idx],
                    "metadata": m,
                    "score": float(s),
                })
                if len(out) >= top_k:
                    break
            return out
        except Exception as e:
            logger.error(f"[Legacy] search failed: {e}")
            return []

    @staticmethod
    def _legacy_delete_document(doc_id):
        _load_legacy()
        i = len(_legacy_data["ids"]) - 1
        while i >= 0:
            if _legacy_data["ids"][i].startswith(f"{doc_id}_chunk_"):
                for k in ("ids", "chunks", "embeddings", "metadata"):
                    _legacy_data[k].pop(i)
            i -= 1
        _save_legacy()

    @staticmethod
    def _legacy_delete_by_kb(knowledge_base_id):
        _load_legacy()
        kb_doc_ids = {m.get("doc_id", "") for m in _legacy_data["metadata"]
                      if m.get("knowledge_base_id", "default") == knowledge_base_id}
        i = len(_legacy_data["ids"]) - 1
        removed = 0
        while i >= 0:
            cid = _legacy_data["ids"][i]
            if any(cid.startswith(f"{d}_chunk_") for d in kb_doc_ids if d):
                for k in ("ids", "chunks", "embeddings", "metadata"):
                    _legacy_data[k].pop(i)
                removed += 1
            i -= 1
        if removed:
            _save_legacy()
        return removed

    @staticmethod
    def _legacy_list_chunks_by_doc(doc_id):
        _load_legacy()
        out = []
        for i, cid in enumerate(_legacy_data["ids"]):
            if cid.startswith(f"{doc_id}_chunk_"):
                out.append({
                    "id": cid,
                    "content": _legacy_data["chunks"][i],
                    "metadata": _legacy_data["metadata"][i],
                })
        return out

    @staticmethod
    def _legacy_list_all_chunks(page, page_size, search, doc_id):
        _load_legacy()
        items = []
        for i, cid in enumerate(_legacy_data["ids"]):
            if doc_id and not cid.startswith(f"{doc_id}_chunk_"):
                continue
            content = _legacy_data["chunks"][i]
            if search and search.lower() not in content.lower():
                continue
            m = _legacy_data["metadata"][i]
            items.append({
                "id": cid,
                "doc_id": m.get("doc_id", ""),
                "title": m.get("title", ""),
                "category": m.get("category", ""),
                "chunk_index": m.get("chunk_index", 0),
                "content": content,
                "dimension": len(_legacy_data["embeddings"][i]) if _legacy_data["embeddings"][i] else 0,
                "metadata": m,
            })
        total = len(items)
        start = (page - 1) * page_size
        return {
            "items": items[start:start + page_size],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if page_size else 0,
        }

    @staticmethod
    def _legacy_get_stats():
        _load_legacy()
        unique_docs = set()
        unique_cats = set()
        for m in _legacy_data["metadata"]:
            if isinstance(m, dict):
                did = m.get("doc_id")
                cat = m.get("category", "默认")
                if did:
                    unique_docs.add(did)
                unique_cats.add(cat)
        return {
            "total_chunks": len(_legacy_data["chunks"]),
            "covered_docs": len(unique_docs),
            "categories": len(unique_cats),
            "collection_name": "knowledge_base_legacy",
            "persist_file": str(JSON_BACKUP_PATH),
        }

    @staticmethod
    def _legacy_count_by_doc_id(doc_id):
        _load_legacy()
        if not doc_id:
            return 0
        prefix = f"{doc_id}_chunk_"
        return sum(1 for cid in _legacy_data["ids"] if cid.startswith(prefix))

    @staticmethod
    def _legacy_count_total():
        _load_legacy()
        return len(_legacy_data["ids"])

    @staticmethod
    def _legacy_update_category(doc_id, new_category):
        _load_legacy()
        prefix = f"{doc_id}_chunk_"
        updated = 0
        for i, cid in enumerate(_legacy_data["ids"]):
            if cid.startswith(prefix):
                _legacy_data["metadata"][i]["category"] = new_category
                updated += 1
        if updated:
            _save_legacy()
        return updated

    @staticmethod
    def _legacy_remove_document(doc_id):
        _load_legacy()
        prefix = f"{doc_id}_chunk_"
        i = len(_legacy_data["ids"]) - 1
        removed = 0
        while i >= 0:
            if _legacy_data["ids"][i].startswith(prefix):
                for k in ("ids", "chunks", "embeddings", "metadata"):
                    _legacy_data[k].pop(i)
                removed += 1
            i -= 1
        if removed:
            _save_legacy()
        return removed

    @staticmethod
    def _legacy_rebuild_index():
        _load_legacy()
        return {"status": "ok", "total_chunks": len(_legacy_data["chunks"])}

    # ============== 主入口：VectorStore 公开 API ==============
    @staticmethod
    def add_document(doc_id: str, chunks: List[str], metadata: List[dict]) -> int:
        """添加文档到向量库。返回实际写入的分块数。"""
        if not chunks:
            return 0
        col = _init_chroma()
        if col is None:
            return VectorStore._legacy_add_document(doc_id, chunks, metadata)
        try:
            service = get_embedding_service_lazy()
            encode_func = getattr(service, "encode_document", service.encode)
            embeddings = list(encode_func(chunks))
            # 0.5.x 的 count() 不支持 where；用 get + len 获取该 doc 已有 chunk 数
            existing = col.get(where={"doc_id": doc_id}, include=[]) if doc_id else {"ids": []}
            existing_count = len(existing.get("ids", []))
            ids = [f"{doc_id}_chunk_{existing_count + i}" for i in range(len(chunks))]
            col.add(
                ids=ids,
                documents=chunks,
                embeddings=embeddings,
                metadatas=[_sanitize_metadata(m) for m in metadata],
            )
            logger.info(f"[Chroma] add_document | doc={doc_id[:8]} | +{len(chunks)} | total={col.count()}")
            return len(chunks)
        except Exception as e:
            logger.error(f"[Chroma] add_document failed: {e}")
            return VectorStore._legacy_add_document(doc_id, chunks, metadata)

    @staticmethod
    def search(query: str, top_k: int = 10,
               categories: Optional[List[str]] = None,
               knowledge_base_id: Optional[str] = None) -> List[dict]:
        """语义搜索。Returns: [{id, content, metadata, score}]"""
        col = _init_chroma()
        if col is None:
            return VectorStore._legacy_search(query, top_k, categories, knowledge_base_id)
        try:
            total = col.count()
            if total == 0:
                return []
            service = get_embedding_service_lazy()
            encode_func = getattr(service, "encode_query", service.encode)
            query_emb = list(encode_func([query])[0])
            where = _build_where(categories, knowledge_base_id)
            fetch_n = min(top_k * 3, total)
            results = col.query(
                query_embeddings=[query_emb],
                n_results=fetch_n,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
            ids = results.get("ids", [[]])[0]
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            dists = results.get("distances", [[]])[0]
            formatted: List[dict] = []
            for i in range(len(ids)):
                sim = max(0.0, 1.0 - float(dists[i]))
                formatted.append({
                    "id": ids[i],
                    "content": docs[i],
                    "metadata": metas[i] or {},
                    "score": sim,
                })
            return formatted[:top_k]
        except Exception as e:
            logger.error(f"[Chroma] search failed: {e}")
            return VectorStore._legacy_search(query, top_k, categories, knowledge_base_id)

    @staticmethod
    def delete_document(doc_id: str) -> None:
        col = _init_chroma()
        if col is None:
            return VectorStore._legacy_delete_document(doc_id)
        try:
            col.delete(where={"doc_id": doc_id})
            logger.info(f"[Chroma] delete_document | doc={doc_id[:8]} | remaining={col.count()}")
        except Exception as e:
            logger.error(f"[Chroma] delete_document failed: {e}")
            VectorStore._legacy_delete_document(doc_id)

    @staticmethod
    def delete_by_kb(knowledge_base_id: str) -> int:
        col = _init_chroma()
        if col is None:
            return VectorStore._legacy_delete_by_kb(knowledge_base_id)
        try:
            if knowledge_base_id == "all":
                # 0.5.x 的 delete 不支持 where={}（匹配所有），先 get 拿所有 ids
                res = col.get(include=[])
                ids = res.get("ids", [])
                if ids:
                    col.delete(ids=ids)
                return len(ids)
            # 0.5.x 的 count() 不支持 where 参数
            res = col.get(where={"knowledge_base_id": knowledge_base_id}, include=[])
            ids = res.get("ids", [])
            if ids:
                col.delete(ids=ids)
            return len(ids)
        except Exception as e:
            logger.error(f"[Chroma] delete_by_kb failed: {e}")
            return VectorStore._legacy_delete_by_kb(knowledge_base_id)

    @staticmethod
    def list_chunks_by_doc(doc_id: str) -> List[dict]:
        col = _init_chroma()
        if col is None:
            return VectorStore._legacy_list_chunks_by_doc(doc_id)
        try:
            res = col.get(where={"doc_id": doc_id}, include=["documents", "metadatas"])
            return [
                {
                    "id": res["ids"][i],
                    "content": res["documents"][i],
                    "metadata": (res["metadatas"][i] or {}),
                }
                for i in range(len(res["ids"]))
            ]
        except Exception as e:
            logger.error(f"[Chroma] list_chunks_by_doc failed: {e}")
            return VectorStore._legacy_list_chunks_by_doc(doc_id)

    @staticmethod
    def list_all_chunks(page: int = 1, page_size: int = 20, search: str = "", doc_id: str = "") -> dict:
        col = _init_chroma()
        if col is None:
            return VectorStore._legacy_list_all_chunks(page, page_size, search, doc_id)
        try:
            where = {"doc_id": doc_id} if doc_id else None
            res = (col.get(where=where, include=["documents", "metadatas"])
                   if where else col.get(include=["documents", "metadatas"]))
            ids = res.get("ids", [])
            docs = res.get("documents", [])
            metas = res.get("metadatas", [])
            dim = 1024
            items = []
            for i, cid in enumerate(ids):
                content = docs[i] or ""
                if search and search.lower() not in content.lower():
                    continue
                m = metas[i] or {}
                items.append({
                    "id": cid,
                    "doc_id": m.get("doc_id", ""),
                    "title": m.get("title", ""),
                    "category": m.get("category", ""),
                    "chunk_index": m.get("chunk_index", 0),
                    "content": content,
                    "dimension": dim,
                    "metadata": m,
                })
            total = len(items)
            start = (page - 1) * page_size
            return {
                "items": items[start:start + page_size],
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size if page_size else 0,
            }
        except Exception as e:
            logger.error(f"[Chroma] list_all_chunks failed: {e}")
            return VectorStore._legacy_list_all_chunks(page, page_size, search, doc_id)

    @staticmethod
    def get_stats() -> dict:
        col = _init_chroma()
        if col is None:
            return VectorStore._legacy_get_stats()
        try:
            total = col.count()
            res = col.get(include=["metadatas"])
            unique_docs = set()
            unique_cats = set()
            for m in res.get("metadatas", []):
                if isinstance(m, dict):
                    did = m.get("doc_id")
                    cat = m.get("category", "默认")
                    if did:
                        unique_docs.add(did)
                    unique_cats.add(cat)
            return {
                "total_chunks": total,
                "covered_docs": len(unique_docs),
                "categories": len(unique_cats),
                "collection_name": COLLECTION_NAME,
                "persist_file": str(CHROMA_PERSIST_DIR),
            }
        except Exception as e:
            logger.error(f"[Chroma] get_stats failed: {e}")
            return VectorStore._legacy_get_stats()

    @staticmethod
    def count_by_doc_id(doc_id: str) -> int:
        if not doc_id:
            return 0
        col = _init_chroma()
        if col is None:
            return VectorStore._legacy_count_by_doc_id(doc_id)
        try:
            # chromadb 0.5.x 的 count() 不支持 where 参数，改用 get + len
            res = col.get(where={"doc_id": doc_id}, include=[])
            return len(res["ids"])
        except Exception as e:
            logger.error(f"[Chroma] count_by_doc_id failed: {e}")
            return VectorStore._legacy_count_by_doc_id(doc_id)

    @staticmethod
    def count_total() -> int:
        col = _init_chroma()
        if col is None:
            return VectorStore._legacy_count_total()
        try:
            return col.count()
        except Exception as e:
            logger.error(f"[Chroma] count_total failed: {e}")
            return VectorStore._legacy_count_total()

    @staticmethod
    def update_category(doc_id: str, new_category: str) -> int:
        if not doc_id:
            return 0
        col = _init_chroma()
        if col is None:
            return VectorStore._legacy_update_category(doc_id, new_category)
        try:
            res = col.get(where={"doc_id": doc_id}, include=[])
            ids = res.get("ids", [])
            if not ids:
                return 0
            for cid in ids:
                col.update(ids=[cid], metadatas=[{"category": new_category}])
            return len(ids)
        except Exception as e:
            logger.error(f"[Chroma] update_category failed: {e}")
            return VectorStore._legacy_update_category(doc_id, new_category)

    @staticmethod
    def remove_document(doc_id: str) -> int:
        if not doc_id:
            return 0
        col = _init_chroma()
        if col is None:
            return VectorStore._legacy_remove_document(doc_id)
        try:
            # 0.5.x 的 count() 不支持 where
            res = col.get(where={"doc_id": doc_id}, include=[])
            ids = res.get("ids", [])
            if ids:
                col.delete(ids=ids)
            return len(ids)
        except Exception as e:
            logger.error(f"[Chroma] remove_document failed: {e}")
            return VectorStore._legacy_remove_document(doc_id)

    @staticmethod
    def rebuild_index():
        col = _init_chroma()
        if col is None:
            return VectorStore._legacy_rebuild_index()
        return {"status": "ok", "total_chunks": col.count()}

    @staticmethod
    def reindex_all_documents():
        """从 SQLite 重新索引所有文档（Chroma 实现）— 任务 P0-2: JSON → SQLite"""
        import time
        t0 = time.time()
        # 任务 P0-2: 优先从 SQLite 读 documents
        try:
            from app.core.db import get_db_session
            from app.core.models import Document
            with get_db_session() as session:
                db_docs = session.query(Document).all()
                docs = {
                    d.id: {
                        "title": d.title, 
                        "content": d.content, 
                        "category": getattr(d, "category", "默认"),
                        "knowledge_base_id": getattr(d, "knowledge_base_id", "default"),
                        **(d.extra_metadata or {})
                    } 
                    for d in db_docs
                }
            if not docs:
                # SQLite 为空 → fallback JSON
                docs_path = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                    "data", "documents.json"
                )
                if os.path.exists(docs_path):
                    with open(docs_path, "r", encoding="utf-8") as f:
                        docs = json.load(f)
        except Exception as e:
            logger.warning(f"[reindex] SQLite read failed, fallback JSON: {e}")
            docs_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "data", "documents.json"
            )
            if not os.path.exists(docs_path):
                return {"status": "error", "msg": f"documents.json not found at {docs_path}"}
            with open(docs_path, "r", encoding="utf-8") as f:
                docs = json.load(f)
        col = _init_chroma()
        if col is None:
            return {"status": "error", "msg": "ChromaDB 不可用"}
        try:
            existing = col.get(include=[])
            if existing["ids"]:
                col.delete(ids=existing["ids"])
                logger.info(f"[reindex] cleared {len(existing['ids'])} old chunks")
        except Exception as e:
            logger.warning(f"[reindex] clear old: {e}")

        from app.core.chunking import ChunkingService
        
        # 强制重新从数据库加载最新分类配置
        from app.core.chunking import _load_categories
        _load_categories()

        total_chunks = 0
        success_docs = 0
        failed_docs = []
        for doc_id, doc in docs.items():
            try:
                content = doc.get("content", "")
                title = doc.get("title", doc_id)
                category = doc.get("category", "默认")
                knowledge_base_id = doc.get("knowledge_base_id", "default")
                if not content:
                    failed_docs.append({"doc_id": doc_id, "reason": "empty content"})
                    continue
                
                # 任务 P2 opt6: 动态策略分块，遵循数据库配置
                chunks = ChunkingService.chunk_text(content, category=category)
                
                if not chunks:
                    failed_docs.append({"doc_id": doc_id, "reason": "no chunks produced"})
                    continue
                metadata_list = [
                    {
                        "doc_id": doc_id,
                        "title": title,
                        "category": category,
                        "knowledge_base_id": knowledge_base_id,
                        "chunk_index": i,
                        "total_chunks": len(chunks),
                    }
                    for i in range(len(chunks))
                ]
                VectorStore.add_document(doc_id, chunks, metadata_list)
                total_chunks += len(chunks)
                success_docs += 1
                logger.info(f"[reindex] {doc_id[:8]} {title[:30]} | {len(chunks)} chunks")
            except Exception as e:
                failed_docs.append({"doc_id": doc_id, "reason": str(e)[:200]})
                logger.error(f"[reindex] FAILED {doc_id}: {e}")

        elapsed = round(time.time() - t0, 2)
        result = {
            "status": "ok",
            "total_docs": len(docs),
            "success_docs": success_docs,
            "failed_docs": len(failed_docs),
            "total_chunks": total_chunks,
            "elapsed_sec": elapsed,
            "failures": failed_docs[:5] if failed_docs else [],
        }
        logger.info(
            f"[reindex] 完成 | docs={success_docs}/{len(docs)} | "
            f"chunks={total_chunks} | elapsed={elapsed}s"
        )
        return result

    @staticmethod
    def reindex_documents(doc_ids: Optional[List[str]] = None):
        return VectorStore.reindex_all_documents()


# 文本分块工具
class TextChunker:
    """文本分块

    任务 P2 opt6：支持多种分块策略
    - fixed: 固定大小分块（默认，向后兼容）
    - recursive: 递归按语义边界分块（任务 P2 推荐）
    - sentence: 按句子分块
    """

    CHUNK_SIZE = 500
    OVERLAP = 100

    @staticmethod
    def chunk_text(text: str, method: str = "fixed") -> List[str]:
        """将文本分块

        Args:
            text: 输入文本
            method: 分块方法
                - "fixed": 固定大小（默认）
                - "recursive": 递归按语义边界
                - "sentence": 按句子
        """
        if not text:
            return []

        if method == "fixed":
            return TextChunker._chunk_fixed(text)
        elif method == "recursive":
            return TextChunker._chunk_recursive(text)
        elif method == "sentence":
            return TextChunker._chunk_sentence(text)
        else:
            return TextChunker._chunk_fixed(text)

    @staticmethod
    def _chunk_fixed(text: str) -> List[str]:
        """固定大小分块（向后兼容）"""
        chunks = []
        start = 0
        while start < len(text):
            end = start + TextChunker.CHUNK_SIZE
            chunk = text[start:end]
            if end < len(text):
                last_punct = max(
                    chunk.rfind('。'),
                    chunk.rfind('？'),
                    chunk.rfind('！'),
                    chunk.rfind('. '),
                    chunk.rfind('\n')
                )
                if last_punct > TextChunker.CHUNK_SIZE * 0.5:
                    chunk = chunk[:last_punct + 1]
                    end = start + len(chunk)
            chunks.append(chunk.strip())
            start = end - TextChunker.OVERLAP
        return [c for c in chunks if c]

    @staticmethod
    def _chunk_recursive(
        text: str,
        chunk_size: int = 500,
        overlap: int = 50,
        separators: Optional[List[str]] = None,
    ) -> List[str]:
        """任务 P2 opt6：递归按语义边界分块

        优先级：段落 > 行 > 中文句末 > 中文分句 > 英文空格 > 字符级

        参考 LangChain RecursiveCharacterTextSplitter 设计
        """
        if separators is None:
            separators = ["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]
        if not text:
            return []
        # 已经短于 chunk_size，直接返回
        if len(text) <= chunk_size:
            return [text.strip()] if text.strip() else []

        sep = separators[0]
        remaining_seps = separators[1:] if len(separators) > 1 else [""]

        # 按当前分隔符拆分
        if sep:
            parts = text.split(sep)
        else:
            # 字符级兜底
            return TextChunker._chunk_recursive(
                text, chunk_size, overlap,
                [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)],
            )

        chunks = []
        current = ""

        for part in parts:
            part_with_sep = part + sep if current else part
            # 如果加上当前 part 会超长
            if len(current) + len(part_with_sep) <= chunk_size:
                current += part_with_sep
            else:
                # current 满了，先加入
                if current.strip():
                    chunks.append(current.strip())
                # 如果 part 自身超长，递归切
                if len(part_with_sep) > chunk_size and remaining_seps:
                    chunks.extend(
                        TextChunker._chunk_recursive(
                            part_with_sep, chunk_size, overlap, remaining_seps,
                        )
                    )
                    current = ""
                else:
                    current = part_with_sep

        if current.strip():
            chunks.append(current.strip())

        # 应用 overlap
        if overlap > 0 and len(chunks) > 1:
            chunks = TextChunker._apply_overlap(chunks, overlap)

        return [c for c in chunks if c]

    @staticmethod
    def _chunk_sentence(text: str, chunk_size: int = 500) -> List[str]:
        """按句子分块（中英文）"""
        import re
        # 按中英文句末标点切
        sentences = re.split(r'(?<=[。！？.!?])\s*', text)
        chunks = []
        current = ""
        for s in sentences:
            if len(current) + len(s) <= chunk_size:
                current += s
            else:
                if current:
                    chunks.append(current.strip())
                current = s
        if current:
            chunks.append(current.strip())
        return [c for c in chunks if c]

    @staticmethod
    def _apply_overlap(chunks: List[str], overlap: int) -> List[str]:
        """为分块添加 overlap（保留前一块尾部）"""
        if overlap <= 0 or len(chunks) <= 1:
            return chunks
        result = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_tail = chunks[i - 1][-overlap:] if len(chunks[i - 1]) > overlap else chunks[i - 1]
            result.append(prev_tail + chunks[i])
        return result

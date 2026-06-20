"""
向量分块 API - v2 需求 9
"""
import csv
import io
import logging
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.core.vector_store import VectorStore

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/list")
async def list_chunks(
    page: int = Query(1, ge=1),
    # 允许前端一次性拉取（最大 5000）；v3 按文档聚合需要全量数据
    page_size: int = Query(20, ge=1, le=5000),
    search: str = Query("", description="在分块内容中搜索"),
    doc_id: str = Query("", description="按文档ID过滤"),
    category: str = Query("", description="按分类过滤"),
):
    """分页列出所有向量分块"""
    result = VectorStore.list_all_chunks(
        page=page, page_size=page_size, search=search, doc_id=doc_id
    )
    if category:
        result["items"] = [it for it in result["items"] if it["category"] == category]
        result["total"] = len(result["items"])
        result["total_pages"] = (result["total"] + page_size - 1) // page_size
    return result


@router.get("/export")
async def export_chunks(
    search: str = Query(""),
    doc_id: str = Query(""),
    category: str = Query(""),
):
    """导出分块为 CSV"""
    result = VectorStore.list_all_chunks(page=1, page_size=100000, search=search, doc_id=doc_id)
    items = result["items"]
    if category:
        items = [it for it in items if it["category"] == category]

    # 生成 CSV
    output = io.StringIO()
    # 加 BOM 让 Excel 正确识别 UTF-8
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow(["分块ID", "文档名称", "分类", "分块序号", "向量维度", "分块内容预览", "创建时间"])
    for it in items:
        writer.writerow([
            it["id"],
            it["title"],
            it["category"],
            it["chunk_index"],
            it["dimension"],
            (it["content"] or "")[:200].replace("\n", " "),
            it["metadata"].get("created_at", ""),
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=chunks.csv"},
    )


@router.get("/stats")
async def chunk_stats():
    """分块统计"""
    all_result = VectorStore.list_all_chunks(page=1, page_size=1000000)
    items = all_result["items"]
    total = all_result["total"]
    # 按 doc 聚合
    by_doc: dict[str, int] = {}
    by_cat: dict[str, int] = {}
    for it in items:
        by_doc[it["title"] or "(未命名)"] = by_doc.get(it["title"] or "(未命名)", 0) + 1
        by_cat[it["category"] or "默认"] = by_cat.get(it["category"] or "默认", 0) + 1
    return {
        "total_chunks": total,
        "total_documents": len(by_doc),
        "total_categories": len(by_cat),
        "by_document": sorted(by_doc.items(), key=lambda x: -x[1])[:10],
        "by_category": sorted(by_cat.items(), key=lambda x: -x[1]),
    }


@router.post("/reindex")
async def reindex_all():
    """任务 P3 opt8：重建全量索引

    从 documents.json 重新索引所有文档到向量库。
    用于：上传了新文档后未自动索引 / 索引不完整 / 调整分块策略。
    """
    result = VectorStore.reindex_all_documents()
    return result


@router.post("/reindex/{doc_id}")
async def reindex_one(doc_id: str):
    """任务 P3 opt8：重建单个文档的索引

    简化实现：先 remove 再 add（保持轻量）
    """
    # 先移除旧 chunks
    VectorStore.remove_document(doc_id)
    # 再重新添加
    import json
    import os
    from app.core.vector_store import TextChunker
    docs_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "data", "documents.json"
    )
    with open(docs_path, "r", encoding="utf-8") as f:
        docs = json.load(f)
    if doc_id not in docs:
        return {"status": "error", "msg": f"doc_id {doc_id} not in documents.json"}
    doc = docs[doc_id]
    content = doc.get("content", "")
    if not content:
        return {"status": "error", "msg": "empty content"}
    chunks = TextChunker.chunk_text(content)
    metadata_list = [
        {
            "doc_id": doc_id,
            "title": doc.get("title", doc_id),
            "category": doc.get("category", "默认"),
            "knowledge_base_id": doc.get("knowledge_base_id", "default"),
            "chunk_index": i,
            "total_chunks": len(chunks),
        }
        for i in range(len(chunks))
    ]
    VectorStore.add_document(doc_id, chunks, metadata_list)
    return {
        "status": "ok",
        "doc_id": doc_id,
        "chunks": len(chunks),
    }

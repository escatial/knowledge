"""
回收站 API
"""
import time
import logging
from fastapi import APIRouter, HTTPException, Query

from app.core.recycle_bin import get_recycle_bin

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/list")
async def list_recycle():
    """列出回收站中的所有文档（未过期）"""
    items = get_recycle_bin().list()
    return {
        "success": True,
        "count": len(items),
        "items": [
            {
                "doc_id": it["doc_id"],
                "title": it["doc_data"].get("title", ""),
                "category": it["doc_data"].get("category", ""),
                "deleted_at": it["deleted_at"],
                "expires_at": it["expires_at"],
                "remaining_days": max(0, round((it["expires_at"] - time.time()) / 86400, 1)),
            }
            for it in items
        ],
    }


@router.post("/restore")
async def restore(doc_id: str = Query(..., description="要恢复的文档ID")):
    """从回收站恢复文档 - 重建文档元数据 + 重建图谱关联"""
    from app.services.document_service import DocumentService
    from app.services.knowledge_graph import kg_service

    item = get_recycle_bin().pop(doc_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"回收站中无此文档 {doc_id}")

    doc_data = item["doc_data"]
    content = item.get("content", "")

    doc_service = DocumentService()
    new_doc = doc_service.save_document_sync(
        filename=doc_data.get("title", doc_id),
        file_content=b"",
        parsed_content=content,
        title=doc_data.get("title"),
        category=doc_data.get("category", "默认"),
    )

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


@router.delete("/{doc_id}")
async def hard_delete(doc_id: str):
    """从回收站永久删除（不可恢复）"""
    item = get_recycle_bin().pop(doc_id)
    if not item:
        return {"success": False, "error": "回收站中无此文档"}
    return {"success": True, "doc_id": doc_id}


@router.post("/cleanup")
async def cleanup():
    """清理回收站过期项（>7天）"""
    removed = get_recycle_bin().cleanup_expired()
    return {"success": True, "removed": removed}

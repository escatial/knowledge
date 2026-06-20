"""任务 P1-2：标签 API"""
import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.tags import (
    create_tag, list_tags, delete_tag, list_tag_categories,
    get_tag, sync_tag_counts,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tags", tags=["tags"])


class CreateTagRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    category: str = "custom"
    color: str = ""
    description: str = ""


@router.get("/categories")
async def get_categories():
    """列出所有标签分类"""
    return {"categories": list_tag_categories()}


@router.get("")
async def list_tags_endpoint(category: Optional[str] = None):
    """列出所有标签（可按 category 过滤）"""
    return {"tags": list_tags(category=category)}


@router.post("")
async def create_tag_endpoint(req: CreateTagRequest):
    """创建标签"""
    try:
        t = create_tag(req.name, req.category, req.color, req.description)
        return {"tag": t}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{name}")
async def get_tag_endpoint(name: str):
    """获取标签详情"""
    t = get_tag(name)
    if not t:
        raise HTTPException(status_code=404, detail="标签不存在")
    return {"tag": t}


@router.delete("/{name}")
async def delete_tag_endpoint(name: str):
    """删除标签"""
    if not delete_tag(name):
        raise HTTPException(status_code=404, detail="标签不存在")
    return {"status": "ok"}


@router.post("/sync-counts")
async def sync_counts_endpoint():
    """根据所有文档的 tag 列表重算 doc_count（管理员工具）"""
    from app.services.document_service import _documents
    doc_tag_lists = []
    for d in _documents.values():
        if isinstance(d, dict):
            doc_tag_lists.append(d.get("tags") or [])
    sync_tag_counts(doc_tag_lists)
    return {"status": "ok", "msg": "标签计数已同步"}


@router.get("/search/by-tag/{tag_name}")
async def docs_by_tag_endpoint(tag_name: str):
    """按标签查找文档"""
    from app.services.document_service import _documents
    tag_name = tag_name.lower().strip()
    docs = []
    for doc_id, doc in _documents.items():
        if isinstance(doc, dict):
            tags = [t.lower() for t in (doc.get("tags") or [])]
            if tag_name in tags:
                docs.append({
                    "id": doc_id,
                    "title": doc.get("title", ""),
                    "category": doc.get("category", ""),
                    "author": doc.get("author", ""),
                })
    return {"tag": tag_name, "doc_count": len(docs), "documents": docs}
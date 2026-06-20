"""任务 P0-3：版本 API

端点：
- GET    /api/documents/{doc_id}/versions                  列出所有版本
- GET    /api/documents/{doc_id}/versions/{v}              获取指定版本
- GET    /api/documents/{doc_id}/diff?from={v1}&to={v2}    对比版本
- POST   /api/documents/{doc_id}/versions/{v}/rollback     回滚
- POST   /api/documents/{doc_id}/versions                  手动创建版本（编辑文档时）
"""
import logging
from fastapi import APIRouter, HTTPException

from app.core.versioning import (
    list_versions, get_version, diff_versions, rollback, create_version,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["versions"])


@router.get("/{doc_id}/versions")
async def list_versions_endpoint(doc_id: str):
    return {"versions": list_versions(doc_id), "doc_id": doc_id}


@router.get("/{doc_id}/versions/{version}")
async def get_version_endpoint(doc_id: str, version: int):
    v = get_version(doc_id, version)
    if not v:
        raise HTTPException(status_code=404, detail=f"版本不存在: v{version}")
    return {"version": v}


@router.get("/{doc_id}/diff")
async def diff_endpoint(doc_id: str, from_v: int, to_v: int):
    """对比 from_v 与 to_v"""
    if from_v == to_v:
        raise HTTPException(status_code=400, detail="from 与 to 不能相同")
    return diff_versions(doc_id, from_v, to_v)


@router.post("/{doc_id}/versions/{version}/rollback")
async def rollback_endpoint(doc_id: str, version: int):
    """回滚到指定版本（创建新版本）"""
    new_v = rollback(doc_id, version, changed_by="")
    if not new_v:
        raise HTTPException(status_code=404, detail=f"版本不存在: v{version}")
    return {"version": {"version": new_v["version"], "created_at": new_v["created_at"]}}
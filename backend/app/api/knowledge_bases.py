"""任务 2：知识库管理 API 端点"""
from fastapi import APIRouter, HTTPException

from app.services.knowledge_base import KnowledgeBaseService

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


@router.get("")
async def list_knowledge_bases():
    """列出所有知识库"""
    return KnowledgeBaseService.list_kbs()


@router.post("")
async def create_knowledge_base(data: dict):
    """创建新知识库

    Body: {"name": "知识库名称", "description": "描述（可选）"}
    """
    name = data.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="知识库名称不能为空")
    try:
        return KnowledgeBaseService.create_kb(name, data.get("description", ""))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.delete("/{kb_id}")
async def delete_knowledge_base(kb_id: str):
    """删除知识库（不能删除默认库）"""
    try:
        return KnowledgeBaseService.delete_kb(kb_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/migrate")
async def migrate_document(data: dict):
    """跨库迁移文档

    Body: {"doc_id": "文档ID", "from_kb": "源知识库ID", "to_kb": "目标知识库ID"}
    """
    doc_id = data.get("doc_id", "")
    from_kb = data.get("from_kb", "")
    to_kb = data.get("to_kb", "")
    if not all([doc_id, from_kb, to_kb]):
        raise HTTPException(status_code=400, detail="缺少必要参数: doc_id, from_kb, to_kb")
    if from_kb == to_kb:
        raise HTTPException(status_code=400, detail="源和目标知识库不能相同")
    try:
        return KnowledgeBaseService.migrate_document(doc_id, from_kb, to_kb)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

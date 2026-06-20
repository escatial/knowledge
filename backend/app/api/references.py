"""任务 P2-2：参考文献 API"""
import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.references import (
    create_reference, list_references, get_reference, format_citation,
    REF_TYPES, attach_refs_to_doc, get_doc_references,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/references", tags=["references"])


class CreateReferenceRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=512)
    authors: List[str] = Field(default_factory=list)
    year: Optional[int] = None
    venue: str = ""
    url: str = ""
    doi: str = ""
    abstract: str = ""
    type: str = "other"


class AttachRequest(BaseModel):
    ref_ids: List[str]


@router.get("/types")
async def list_types():
    return {"types": [{"name": k, **v} for k, v in REF_TYPES.items()]}


@router.get("")
async def list_refs_endpoint(type: Optional[str] = None):
    return {"references": list_references(ref_type=type)}


@router.post("")
async def create_ref_endpoint(req: CreateReferenceRequest):
    try:
        r = create_reference(
            title=req.title, authors=req.authors, year=req.year,
            venue=req.venue, url=req.url, doi=req.doi,
            abstract=req.abstract, ref_type=req.type,
        )
        return {"reference": r}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{ref_id}")
async def get_ref_endpoint(ref_id: str):
    r = get_reference(ref_id)
    if not r:
        raise HTTPException(status_code=404, detail="参考文献不存在")
    return {"reference": r}


@router.get("/{ref_id}/citation")
async def citation_endpoint(ref_id: str, style: str = "apa"):
    r = get_reference(ref_id)
    if not r:
        raise HTTPException(status_code=404, detail="参考文献不存在")
    return {"ref_id": ref_id, "style": style, "citation": format_citation(r, style)}


@router.post("/{doc_id}/attach")
async def attach_endpoint(doc_id: str, req: AttachRequest):
    if not attach_refs_to_doc(doc_id, req.ref_ids):
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"status": "ok", "doc_id": doc_id, "ref_count": len(req.ref_ids)}


@router.get("/doc/{doc_id}")
async def doc_refs_endpoint(doc_id: str):
    refs = get_doc_references(doc_id)
    return {"doc_id": doc_id, "references": refs, "count": len(refs)}
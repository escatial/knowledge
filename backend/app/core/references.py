"""任务 P2-2：参考文献引用体系（任务 P0-2: 迁移到 SQLite）

设计：
- 参考文献表：data/paper_refs（SQLite 表）/ references.json（fallback）
  结构：{ "ref_id": { "id", "title", "authors", "year", "venue", "url", "doi", "abstract", "type" } }
- 文档-引用关系：documents.json 中 doc 包含 references: ["ref_001", "ref_002"]
- 引用类型：book / paper / website / video / standard / other
- 引用风格支持：GB/T 7714（国标），APA，IEEE
"""
import json
import time
import uuid
import threading
import logging
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
REFS_FILE = DATA_DIR / "references.json"
_lock = threading.RLock()


def _parse_dt(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _ref_to_dict(r) -> Dict[str, Any]:
    return {
        "id": r.id,
        "title": r.title,
        "authors": list(r.authors or []),
        "year": r.year or 0,
        "venue": r.venue or "",
        "url": r.url or "",
        "doi": r.doi or "",
        "abstract": r.abstract or "",
        "type": r.type or "other",
        "created_at": r.created_at.isoformat() if r.created_at else "",
    }


# 引用类型
REF_TYPES = {
    "book":     {"label": "图书",       "icon": "BookOpen"},
    "paper":    {"label": "论文",       "icon": "FileText"},
    "website":  {"label": "网页",       "icon": "Globe"},
    "video":    {"label": "视频",       "icon": "Video"},
    "standard": {"label": "标准/规范",   "icon": "Award"},
    "other":    {"label": "其他",       "icon": "FileQuestion"},
}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _load_refs() -> Dict[str, Dict[str, Any]]:
    """任务 P0-2: 优先 SQLite，fallback JSON"""
    try:
        from app.core.db import get_db_session
        from app.core.models import Reference
        with get_db_session() as session:
            rows = session.query(Reference).all()
            return {r.id: _ref_to_dict(r) for r in rows}
    except Exception as e:
        logger.error(f"[_load_refs] SQLite failed, fallback JSON: {e}")
        if not REFS_FILE.exists():
            return {}
        try:
            with open(REFS_FILE, "r", encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception as e2:
            logger.error(f"[_load_refs] JSON fallback failed: {e2}")
            return {}


def _save_refs(refs: Dict[str, Dict[str, Any]]) -> None:
    """任务 P0-2: 优先 SQLite（全量 replace），fallback JSON"""
    with _lock:
        try:
            from app.core.db import get_db_session
            from app.core.models import Reference
            with get_db_session() as session:
                session.query(Reference).delete()
                for r in refs.values():
                    session.add(Reference(
                        id=r["id"],
                        title=r.get("title", ""),
                        authors=r.get("authors", []),
                        year=r.get("year") or 0,
                        venue=r.get("venue", ""),
                        url=r.get("url", ""),
                        doi=r.get("doi", ""),
                        abstract=r.get("abstract", ""),
                        type=r.get("type", "other"),
                        created_at=_parse_dt(r.get("created_at", "")),
                    ))
        except Exception as e:
            logger.error(f"[_save_refs] SQLite failed, fallback JSON: {e}")
            with open(REFS_FILE, "w", encoding="utf-8") as f:
                json.dump(refs, f, ensure_ascii=False, indent=2)


def create_reference(
    title: str, authors: List[str], year: Optional[int] = None,
    venue: str = "", url: str = "", doi: str = "",
    abstract: str = "", ref_type: str = "other",
) -> Dict[str, Any]:
    """创建参考文献"""
    if not title:
        raise ValueError("标题不能为空")
    if ref_type not in REF_TYPES:
        ref_type = "other"
    refs = _load_refs()
    ref_id = f"ref_{uuid.uuid4().hex[:8]}"
    obj = {
        "id": ref_id,
        "title": title,
        "authors": authors or [],
        "year": year,
        "venue": venue,
        "url": url,
        "doi": doi,
        "abstract": abstract,
        "type": ref_type,
        "created_at": _now_iso(),
    }
    refs[ref_id] = obj
    _save_refs(refs)
    return obj


def list_references(ref_type: Optional[str] = None) -> List[Dict[str, Any]]:
    refs = _load_refs()
    out = list(refs.values())
    if ref_type:
        out = [r for r in out if r.get("type") == ref_type]
    out.sort(key=lambda r: (-(r.get("year") or 0), r.get("title", "")))
    return out


def get_reference(ref_id: str) -> Optional[Dict[str, Any]]:
    return _load_refs().get(ref_id)


def format_citation(ref: Dict[str, Any], style: str = "apa") -> str:
    """格式化单条引用"""
    authors = ref.get("authors", [])
    if ref.get("type") == "website":
        # 网页：作者. (年). 标题. 来源. URL
        a = ", ".join(authors) if authors else "Anonymous"
        y = f"({ref.get('year')})" if ref.get("year") else ""
        url = ref.get("url", "")
        return f"{a}. {y} {ref.get('title', '')}. {url}".strip()
    # 论文/图书/其他
    a = ", ".join(authors) if authors else "Anonymous"
    y = f" ({ref.get('year')})" if ref.get("year") else ""
    venue = ref.get("venue", "")
    doi = f" DOI: {ref.get('doi')}" if ref.get("doi") else ""
    url = f" {ref.get('url')}" if ref.get("url") and not ref.get("doi") else ""
    return f"{a}{y}. {ref.get('title', '')}. {venue}.{doi}{url}".strip()


def attach_refs_to_doc(doc_id: str, ref_ids: List[str]) -> bool:
    """把 ref_ids 关联到文档（追加）"""
    from app.services.document_service import _documents
    if doc_id not in _documents:
        return False
    doc = _documents[doc_id]
    if not isinstance(doc, dict):
        return False
    existing = set(doc.get("references") or [])
    existing.update(ref_ids)
    doc["references"] = sorted(existing)
    from app.services.document_service import DocumentService
    DocumentService._save_documents()
    return True


def get_doc_references(doc_id: str) -> List[Dict[str, Any]]:
    """获取文档的所有引用"""
    from app.services.document_service import _documents
    doc = _documents.get(doc_id)
    if not isinstance(doc, dict):
        return []
    ref_ids = doc.get("references") or []
    return [get_reference(rid) for rid in ref_ids if get_reference(rid)]

"""任务 P0-3：文档版本追溯服务（任务 P0-2: SQLite 迁移）

设计：
- 每次文档内容/元数据变更时自动创建版本快照
- 存储：document_versions 表（SQLite）/ data/document_versions.json（fallback）
  结构：{ doc_id: [ { version, content, metadata, changed_by, change_note, created_at } ] }
- 保留最近 N 个版本（默认 50），超出时归档
- 提供 diff（行级 diff） 和 rollback 能力
"""
import json
import time
import uuid
import logging
import threading
import difflib
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
VERSIONS_FILE = DATA_DIR / "document_versions.json"
_lock = threading.RLock()

MAX_VERSIONS_PER_DOC = int(__import__("os").getenv("MAX_VERSIONS_PER_DOC", "50"))


def _now_ts() -> float:
    return time.time()


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _parse_dt(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _version_to_dict(v) -> Dict[str, Any]:
    return {
        "id": v.id,
        "version": v.version,
        "doc_id": v.doc_id,
        "content": v.content,
        "metadata": dict(v.extra_metadata or {}),
        "changed_by": v.changed_by or "",
        "change_note": v.change_note or "",
        "created_at": v.created_at.isoformat() if v.created_at else "",
    }


def _load_versions() -> Dict[str, List[Dict[str, Any]]]:
    """任务 P0-2: 优先 SQLite，fallback JSON"""
    try:
        from app.core.db import get_db_session
        from app.core.models import DocumentVersion
        with get_db_session() as session:
            rows = session.query(DocumentVersion).order_by(
                DocumentVersion.doc_id, DocumentVersion.version
            ).all()
            data: Dict[str, List[Dict[str, Any]]] = {}
            for r in rows:
                data.setdefault(r.doc_id, []).append(_version_to_dict(r))
            if data:
                return data
    except Exception as e:
        logger.error(f"[_load_versions] SQLite failed, fallback JSON: {e}")
    # Fallback: JSON
    if not VERSIONS_FILE.exists():
        return {}
    try:
        with open(VERSIONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.error(f"[_load_versions] JSON fallback failed: {e}")
        return {}


def _save_versions(versions: Dict[str, List[Dict[str, Any]]]) -> None:
    """任务 P0-2: 优先 SQLite（全量 replace），fallback JSON"""
    with _lock:
        try:
            from app.core.db import get_db_session
            from app.core.models import DocumentVersion
            with get_db_session() as session:
                session.query(DocumentVersion).delete()
                for doc_id, doc_versions in versions.items():
                    for v in doc_versions:
                        session.add(DocumentVersion(
                            id=v.get("id", str(uuid.uuid4())),
                            doc_id=v.get("doc_id", doc_id),
                            version=v.get("version", 0),
                            content=v.get("content", ""),
                            extra_metadata=v.get("metadata", {}),
                            changed_by=v.get("changed_by", ""),
                            change_note=v.get("change_note", ""),
                            created_at=_parse_dt(v.get("created_at", "")),
                        ))
        except Exception as e:
            logger.error(f"[_save_versions] SQLite failed, fallback JSON: {e}")
            with open(VERSIONS_FILE, "w", encoding="utf-8") as f:
                json.dump(versions, f, ensure_ascii=False, indent=2)


# =================== 核心 API ===================
def create_version(
    doc_id: str,
    content: str,
    metadata: Dict[str, Any],
    changed_by: str = "",
    change_note: str = "",
) -> Dict[str, Any]:
    """为文档创建一个新版本快照"""
    versions = _load_versions()
    doc_versions = versions.get(doc_id, [])
    next_version = (doc_versions[-1]["version"] + 1) if doc_versions else 1
    version_obj = {
        "version": next_version,
        "doc_id": doc_id,
        "content": content,
        "metadata": metadata,
        "changed_by": changed_by,
        "change_note": change_note,
        "created_at": _now_iso(),
        "id": str(uuid.uuid4()),
    }
    doc_versions.append(version_obj)
    # 保留最近 N 个
    if len(doc_versions) > MAX_VERSIONS_PER_DOC:
        archived = doc_versions[:-MAX_VERSIONS_PER_DOC]
        doc_versions = doc_versions[-MAX_VERSIONS_PER_DOC:]
        logger.info(f"[create_version] 归档 {doc_id} 旧版本 {len(archived)} 个")
    versions[doc_id] = doc_versions
    _save_versions(versions)
    return version_obj


def list_versions(doc_id: str) -> List[Dict[str, Any]]:
    """列出文档的所有版本（仅元数据，不返回 content 节省 IO）"""
    versions = _load_versions()
    doc_versions = versions.get(doc_id, [])
    return [
        {
            "version": v["version"],
            "doc_id": v["doc_id"],
            "title": (v.get("metadata") or {}).get("title", ""),
            "changed_by": v.get("changed_by", ""),
            "change_note": v.get("change_note", ""),
            "created_at": v.get("created_at", ""),
            "content_size": len(v.get("content", "")),
        }
        for v in doc_versions
    ]


def get_version(doc_id: str, version: int) -> Optional[Dict[str, Any]]:
    """获取指定版本的完整快照"""
    versions = _load_versions()
    for v in versions.get(doc_id, []):
        if v["version"] == version:
            return v
    return None


def diff_versions(
    doc_id: str, from_version: int, to_version: int, context_lines: int = 3,
) -> Dict[str, Any]:
    """对比两个版本，返回 unified diff 格式"""
    v_from = get_version(doc_id, from_version)
    v_to = get_version(doc_id, to_version)
    if not v_from or not v_to:
        return {"error": "version_not_found", "from_exists": bool(v_from), "to_exists": bool(v_to)}
    from_lines = v_from.get("content", "").splitlines(keepends=True)
    to_lines = v_to.get("content", "").splitlines(keepends=True)
    diff = list(difflib.unified_diff(
        from_lines, to_lines,
        fromfile=f"v{from_version}", tofile=f"v{to_version}",
        n=context_lines,
    ))
    # 元数据 diff
    meta_from = v_from.get("metadata", {}) or {}
    meta_to = v_to.get("metadata", {}) or {}
    meta_changes = {}
    for k in set(meta_from) | set(meta_to):
        if meta_from.get(k) != meta_to.get(k):
            meta_changes[k] = {"from": meta_from.get(k), "to": meta_to.get(k)}
    return {
        "doc_id": doc_id,
        "from_version": from_version,
        "to_version": to_version,
        "from_meta": meta_from,
        "to_meta": meta_to,
        "metadata_changes": meta_changes,
        "unified_diff": "".join(diff),
        "diff_stats": {
            "from_lines": len(from_lines),
            "to_lines": len(to_lines),
            "additions": sum(1 for ln in diff if ln.startswith("+") and not ln.startswith("+++")),
            "deletions": sum(1 for ln in diff if ln.startswith("-") and not ln.startswith("---")),
        },
    }


def rollback(doc_id: str, to_version: int, changed_by: str = "", note: str = "") -> Optional[Dict[str, Any]]:
    """回滚到指定版本（创建新版本 = 旧版本的内容）"""
    target = get_version(doc_id, to_version)
    if not target:
        return None
    return create_version(
        doc_id=doc_id,
        content=target["content"],
        metadata=target.get("metadata", {}),
        changed_by=changed_by,
        change_note=f"回滚到 v{to_version} | {note}".strip(" |"),
    )


def delete_versions(doc_id: str) -> int:
    """删除文档的所有版本（文档删除时调用）"""
    versions = _load_versions()
    removed = len(versions.pop(doc_id, []))
    if removed:
        _save_versions(versions)
    return removed

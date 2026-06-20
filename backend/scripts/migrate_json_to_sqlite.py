"""一次性把 7 个 JSON 导入 SQLite

用法：
    python scripts/migrate_json_to_sqlite.py

注意：
- 先确认 init_db.py 已经建表
- 保留 JSON 作为 backup（不删）
- 用 utf-8 + 错误友好（缺字段用默认值）
"""
import sys
import json
import logging
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import init_db, get_db_session, DB_PATH
from app.core.models import (
    User, Document, DocumentVersion, Category, Reference, OpLog, ChatStat
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _parse_dt(s: str):
    """解析 ISO datetime"""
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def migrate_users(session):
    """users.json → users 表"""
    src = DATA_DIR / "users.json"
    if not src.exists():
        logger.warning("  [users] users.json not found, skip")
        return 0
    data = json.loads(src.read_text(encoding="utf-8"))
    count = 0
    for uid, u in data.items():
        if session.query(User).filter_by(id=uid).first():
            continue
        session.add(User(
            id=u.get("id", uid),
            username=u["username"],
            password_hash=u["password_hash"],
            email=u.get("email", ""),
            display_name=u.get("display_name", ""),
            roles=u.get("roles", []),
            status=u.get("status", "active"),
            created_at=_parse_dt(u.get("created_at", "")),
            last_login=_parse_dt(u.get("last_login", "")),
        ))
        count += 1
    return count


def migrate_documents(session):
    """documents.json → documents 表（最大 365 KB）"""
    src = DATA_DIR / "documents.json"
    if not src.exists():
        logger.warning("  [documents] documents.json not found, skip")
        return 0
    data = json.loads(src.read_text(encoding="utf-8"))
    count = 0
    for doc_id, d in data.items():
        if session.query(Document).filter_by(id=doc_id).first():
            continue
        # 推断 extra_metadata（剔除 content/title 后的所有字段）
        meta = {k: v for k, v in d.items() if k not in ("title", "content")}
        session.add(Document(
            id=doc_id,
            title=d.get("title", ""),
            content=d.get("content", ""),
            knowledge_base_id=d.get("knowledge_base_id", "default"),
            file_name=d.get("file_name", ""),
            file_type=d.get("file_type", ""),
            category=d.get("category", ""),
            extra_metadata=meta,
            created_at=_parse_dt(d.get("created_at", "")),
            updated_at=_parse_dt(d.get("updated_at", "")),
        ))
        count += 1
    return count


def migrate_document_versions(session):
    """document_versions.json → document_versions 表"""
    src = DATA_DIR / "document_versions.json"
    if not src.exists():
        logger.warning("  [document_versions] document_versions.json not found, skip")
        return 0
    data = json.loads(src.read_text(encoding="utf-8"))
    count = 0
    for doc_id, versions in data.items():
        for v in versions:
            if session.query(DocumentVersion).filter_by(id=v.get("id", "")).first():
                continue
            session.add(DocumentVersion(
                id=v.get("id", f"{doc_id}-v{v.get('version', 0)}"),
                doc_id=v.get("doc_id", doc_id),
                version=v.get("version", 0),
                content=v.get("content", ""),
                extra_metadata=v.get("metadata", {}),
                changed_by=v.get("changed_by", ""),
                change_note=v.get("change_note", ""),
                created_at=_parse_dt(v.get("created_at", "")),
            ))
            count += 1
    return count


def migrate_categories(session):
    """categories.json → categories 表"""
    src = DATA_DIR / "categories.json"
    if not src.exists():
        logger.warning("  [categories] categories.json not found, skip")
        return 0
    data = json.loads(src.read_text(encoding="utf-8"))
    count = 0
    for name, c in data.items():
        if session.query(Category).filter_by(id=name).first():
            continue
        session.add(Category(
            id=name,
            strategy=c.get("strategy", "recursive"),
            chunk_size=c.get("chunk_size", 500),
            overlap=c.get("overlap", 100),
        ))
        count += 1
    return count


def migrate_references(session):
    """references.json → references 表"""
    src = DATA_DIR / "references.json"
    if not src.exists():
        logger.warning("  [references] references.json not found, skip")
        return 0
    data = json.loads(src.read_text(encoding="utf-8"))
    count = 0
    for rid, r in data.items():
        if session.query(Reference).filter_by(id=rid).first():
            continue
        session.add(Reference(
            id=r.get("id", rid),
            title=r.get("title", ""),
            authors=r.get("authors", []),
            year=r.get("year", 0),
            venue=r.get("venue", ""),
            url=r.get("url", ""),
            doi=r.get("doi", ""),
            type=r.get("type", "paper"),
            abstract=r.get("abstract", ""),
            created_at=_parse_dt(r.get("created_at", "")),
        ))
        count += 1
    return count


def migrate_op_log(session):
    """op_log.json → op_log 表（55 条）"""
    src = DATA_DIR / "op_log.json"
    if not src.exists():
        logger.warning("  [op_log] op_log.json not found, skip")
        return 0
    data = json.loads(src.read_text(encoding="utf-8"))
    count = 0
    for entry in data:
        session.add(OpLog(
            time=_parse_dt(entry.get("time", "")) or datetime.now(),
            operator=entry.get("operator", ""),
            action=entry.get("action", ""),
            doc_ids=entry.get("doc_ids", []),
            target=entry.get("target", ""),
            migrated_count=entry.get("migrated_count", 0),
            skipped_count=entry.get("skipped_count", 0),
            chunks_updated=entry.get("chunks_updated", 0),
            extra={k: v for k, v in entry.items() if k not in (
                "time", "operator", "action", "doc_ids", "target",
                "migrated_count", "skipped_count", "chunks_updated"
            )},
        ))
        count += 1
    return count


def migrate_chat_stats(session):
    """chat_stats.json → chat_stats 表（永远 1 行）"""
    src = DATA_DIR / "chat_stats.json"
    if not src.exists():
        logger.warning("  [chat_stats] chat_stats.json not found, skip")
        return 0
    data = json.loads(src.read_text(encoding="utf-8"))
    # 永远 id=1
    if session.query(ChatStat).filter_by(id=1).first():
        return 0
    session.add(ChatStat(
        id=1,
        total_sessions=data.get("total_sessions", 0),
        total_messages=data.get("total_messages", 0),
    ))
    return 1


if __name__ == "__main__":
    logger.info(f"[migrate] DB: {DB_PATH}")
    init_db()
    logger.info("[migrate] starting...")

    migrators = [
        ("users", migrate_users),
        ("categories", migrate_categories),
        ("references", migrate_references),
        ("documents", migrate_documents),
        ("document_versions", migrate_document_versions),
        ("op_log", migrate_op_log),
        ("chat_stats", migrate_chat_stats),
    ]

    with get_db_session() as session:
        for name, fn in migrators:
            try:
                count = fn(session)
                logger.info(f"  ✓ {name:25s} +{count} rows")
            except Exception as e:
                logger.error(f"  ✗ {name:25s} FAILED: {e}")
                raise

    logger.info("[migrate] done!")

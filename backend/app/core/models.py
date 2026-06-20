"""SQLAlchemy ORM models（任务 P0-2：JSON → SQLite 迁移）

6 张表设计：
- documents: 文档元数据（22 条）
- document_versions: 文档版本历史
- categories: 文档分类 + chunk 策略
- references: 学术引用库
- op_log: 操作审计日志
- chat_stats: 聊天统计
"""
from sqlalchemy import (
    Column, String, Integer, Text, DateTime, JSON, Boolean, Index
)
from sqlalchemy.sql import func
from app.core.db import Base


class Document(Base):
    """文档元数据表 - 替代 documents.json（最大 365 KB）"""
    __tablename__ = "documents"

    id = Column(String(36), primary_key=True)  # doc_id
    title = Column(String(512), nullable=False, index=True)
    content = Column(Text, nullable=False)  # 文档原始文本
    knowledge_base_id = Column(String(64), default="default", index=True)
    file_name = Column(String(512), default="")
    file_type = Column(String(32), default="")
    category = Column(String(64), default="", index=True)  # 对应 categories.json
    extra_metadata = Column(JSON, default=dict)  # 其他元数据
    created_at = Column(DateTime, server_default=func.current_timestamp())
    updated_at = Column(DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp())


class DocumentVersion(Base):
    """文档版本历史 - 替代 document_versions.json"""
    __tablename__ = "document_versions"

    id = Column(String(36), primary_key=True)  # version instance id
    doc_id = Column(String(64), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    extra_metadata = Column(JSON, default=dict)  # 对应原 metadata 字段
    changed_by = Column(String(64), default="")
    change_note = Column(String(512), default="")
    created_at = Column(DateTime, server_default=func.current_timestamp())


class Category(Base):
    """分类 + chunk 策略 - 替代 categories.json"""
    __tablename__ = "categories"

    id = Column(String(64), primary_key=True)  # 分类名（"默认" / "agent"）
    strategy = Column(String(32), default="recursive")
    chunk_size = Column(Integer, default=500)
    overlap = Column(Integer, default=100)
    created_at = Column(DateTime, server_default=func.current_timestamp())


class Reference(Base):
    """学术引用 - 替代 references.json"""
    __tablename__ = "paper_refs"  # 避免 'references' 是 SQLite 保留字

    id = Column(String(64), primary_key=True)  # ref_attention / ref_rag_survey
    title = Column(String(512), nullable=False, index=True)
    authors = Column(JSON, default=list)  # list of strings
    year = Column(Integer, default=0)
    venue = Column(String(255), default="")
    url = Column(String(1024), default="")
    doi = Column(String(255), default="")
    type = Column(String(32), default="paper")
    abstract = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.current_timestamp())


class OpLog(Base):
    """操作审计日志 - 替代 op_log.json (list[55])"""
    __tablename__ = "op_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    time = Column(DateTime, nullable=False, index=True)
    operator = Column(String(64), default="", index=True)
    action = Column(String(64), nullable=False, index=True)  # migrate_batch / update / delete
    doc_ids = Column(JSON, default=list)  # 涉及的文档 id 列表
    target = Column(String(255), default="")  # 目标 KB / 分类
    migrated_count = Column(Integer, default=0)
    skipped_count = Column(Integer, default=0)
    chunks_updated = Column(Integer, default=0)
    extra = Column(JSON, default=dict)  # 其他字段


class ChatStat(Base):
    """聊天统计 - 替代 chat_stats.json"""
    __tablename__ = "chat_stats"

    id = Column(Integer, primary_key=True, default=1)  # always 1
    total_sessions = Column(Integer, default=0)
    total_messages = Column(Integer, default=0)
    updated_at = Column(DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp())


# 复合索引（优化查询）
Index("idx_doc_kb_category", Document.knowledge_base_id, Document.category)
Index("idx_oplog_time_action", OpLog.time, OpLog.action)
Index("idx_version_doc_version", DocumentVersion.doc_id, DocumentVersion.version)

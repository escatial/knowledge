"""
文档服务（任务 P0-2: SQLite 迁移）
"""
import uuid
import json
import os
from datetime import datetime
from pathlib import Path
from typing import List

from app.models.document import Document
from app.core.config import settings

# 存储路径
UPLOAD_DIR = Path(settings.UPLOAD_DIR)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
DOCS_FILE = DATA_DIR / "documents.json"

# 内存缓存（性能优化层；权威存储已迁到 SQLite）
_documents: dict[str, Document] = {}


def _doc_to_dict(doc: Document) -> dict:
    """Document Pydantic → ORM dict"""
    d = doc.model_dump() if hasattr(doc, "model_dump") else doc.dict()
    # 移除 ORM 不直接支持的字段（_sa_instance_state 等）
    d = {k: v for k, v in d.items() if not k.startswith("_")}
    return d


def _doc_dict_to_orm(d: dict) -> dict:
    """dict → ORM 字段映射"""
    # knowledge_base_id 直接对应
    return d


def load_documents():
    """任务 P0-2: 优先 SQLite，fallback JSON"""
    # 优先 SQLite
    try:
        from app.core.db import get_db_session
        from app.core.models import Document as DBDocument
        with get_db_session() as session:
            rows = session.query(DBDocument).all()
            if rows:
                for r in rows:
                    d = {
                        "id": r.id,
                        "title": r.title,
                        "content": r.content,
                        "category": r.category or "",
                        "knowledge_base_id": r.knowledge_base_id or "default",
                        "file_name": r.file_name or "",
                        "file_type": r.file_type or "",
                        "owner": (r.extra_metadata or {}).get("owner", ""),
                        "filename": (r.extra_metadata or {}).get("filename", ""),
                        "created_at": r.created_at or datetime.now(),
                        "updated_at": r.updated_at or datetime.now(),
                    }
                    _documents[r.id] = Document(**d)
                print(f"[load_documents] 从 SQLite 加载 {len(rows)} 个文档")
                return
    except Exception as e:
        print(f"[load_documents] SQLite failed, fallback JSON: {e}")
    # Fallback: JSON
    if DOCS_FILE.exists():
        try:
            with open(DOCS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for doc_id, doc_dict in data.items():
                    if "created_at" in doc_dict and isinstance(doc_dict["created_at"], str):
                        doc_dict["created_at"] = datetime.fromisoformat(doc_dict["created_at"])
                    if "updated_at" in doc_dict and isinstance(doc_dict["updated_at"], str):
                        doc_dict["updated_at"] = datetime.fromisoformat(doc_dict["updated_at"])
                    _documents[doc_id] = Document(**doc_dict)
                print(f"[load_documents] 从 JSON 加载 {len(data)} 个文档")
        except Exception as e:
            print(f"加载文档列表失败: {e}")


def save_documents():
    """任务 P0-2: 优先 SQLite（全量 replace），fallback JSON"""
    # 优先 SQLite
    try:
        from app.core.db import get_db_session
        from app.core.models import Document as DBDocument
        with get_db_session() as session:
            session.query(DBDocument).delete()
            for doc_id, doc in _documents.items():
                d = _doc_to_dict(doc)
                # 推断 file_name/file_type（如果 doc 有这些字段）
                file_name = d.get("filename") or d.get("file_name") or ""
                file_type = d.get("file_type") or ""
                # extra_metadata（除了标准字段外）
                meta = {k: v for k, v in d.items() if k not in {
                    "id", "title", "content", "category", "knowledge_base_id",
                    "file_name", "file_type", "created_at", "updated_at"
                }}
                session.add(DBDocument(
                    id=doc_id,
                    title=d.get("title", ""),
                    content=d.get("content", ""),
                    knowledge_base_id=d.get("knowledge_base_id", "default"),
                    file_name=file_name,
                    file_type=file_type,
                    category=d.get("category", ""),
                    extra_metadata=meta,
                    created_at=d.get("created_at") if isinstance(d.get("created_at"), datetime) else None,
                    updated_at=d.get("updated_at") if isinstance(d.get("updated_at"), datetime) else None,
                ))
        return
    except Exception as e:
        print(f"[save_documents] SQLite failed, fallback JSON: {e}")
    # Fallback: JSON
    try:
        data = {}
        for doc_id, doc in _documents.items():
            doc_dict = doc.model_dump() if hasattr(doc, 'model_dump') else doc.dict()
            if isinstance(doc_dict.get("created_at"), datetime):
                doc_dict["created_at"] = doc_dict["created_at"].isoformat()
            if isinstance(doc_dict.get("updated_at"), datetime):
                doc_dict["updated_at"] = doc_dict["updated_at"].isoformat()
            data[doc_id] = doc_dict
        with open(DOCS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存文档列表失败: {e}")

# 初始化加载
load_documents()

class DocumentService:
    def save_document_sync(self, filename: str, file_content: bytes, parsed_content: str, title: str = None, category: str = "default", owner: str = None, knowledge_base_id: str = "default") -> Document:
        """保存文档（同步版本）"""
        doc_id = str(uuid.uuid4())

        # 保存原始文件
        file_path = UPLOAD_DIR / f"{doc_id}_{filename}"
        with open(file_path, "wb") as f:
            f.write(file_content)

        # 提取扩展名作为 file_type
        file_type = ""
        if "." in filename:
            file_type = filename.rsplit(".", 1)[-1].lower()

        doc = Document(
            id=doc_id,
            title=title or filename,
            content=parsed_content,
            category=category,
            knowledge_base_id=knowledge_base_id,
            filename=filename,
            file_type=file_type,
            owner=owner,
            created_at=datetime.now()
        )

        _documents[doc_id] = doc
        save_documents()
        return doc
    
    def get_documents(self, category: str = None) -> List[Document]:
        """获取文档列表"""
        docs = list(_documents.values())
        if category:
            docs = [d for d in docs if d.category == category]
        return docs
    
    def get_document(self, doc_id: str) -> Document:
        """获取单个文档"""
        return _documents.get(doc_id)

    def delete_document(self, doc_id: str):
        """删除文档"""
        if doc_id in _documents:
            del _documents[doc_id]
            save_documents()

    def update_document_category(self, doc_id: str, category: str) -> bool:
        """更新文档的分类（仅修改元数据，不触发向量化）"""
        doc = _documents.get(doc_id)
        if not doc:
            return False
        doc.category = category
        save_documents()
        return True

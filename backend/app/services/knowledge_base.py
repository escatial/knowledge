"""任务 2：知识库层级架构

- 知识库 CRUD
- 跨库迁移
- 操作日志
- 物理隔离（每库独立 graph.json）
"""
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.services.knowledge_graph import _graph_file_for_kb

logger = logging.getLogger(__name__)

KB_FILE = Path(settings.GRAPH_DATA_DIR) / "knowledge_bases.json"
KB_LOG_FILE = Path(settings.GRAPH_DATA_DIR) / "kb_operations.log"

KB_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load_kbs() -> list[dict]:
    if KB_FILE.exists():
        return json.loads(KB_FILE.read_text(encoding="utf-8"))
    return []


def _save_kbs(kbs: list[dict]):
    KB_FILE.write_text(json.dumps(kbs, ensure_ascii=False, indent=2), encoding="utf-8")


def _log_kb_op(action: str, kb_id: str, detail: str = ""):
    ts = datetime.now().isoformat()
    entry = f"[{ts}] {action} | kb={kb_id} | {detail}\n"
    with open(KB_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(entry)


class KnowledgeBaseService:
    """知识库管理服务"""

    @staticmethod
    def list_kbs() -> list[dict]:
        return _load_kbs()

    @staticmethod
    def get_kb(kb_id: str) -> Optional[dict]:
        for kb in _load_kbs():
            if kb["id"] == kb_id:
                return kb
        return None

    @staticmethod
    def create_kb(name: str, description: str = "") -> dict:
        kbs = _load_kbs()
        if any(kb["name"] == name for kb in kbs):
            raise ValueError(f"知识库「{name}」已存在")
        kb = {
            "id": str(uuid.uuid4())[:8],
            "name": name,
            "description": description,
            "created_at": datetime.now().isoformat(),
            "doc_count": 0,
        }
        kbs.append(kb)
        _save_kbs(kbs)
        _log_kb_op("CREATE", kb["id"], f"name={name}")
        return kb

    @staticmethod
    def delete_kb(kb_id: str) -> dict:
        if kb_id == "default":
            raise ValueError("不能删除默认知识库")
        kbs = _load_kbs()
        target = None
        new_kbs = []
        for kb in kbs:
            if kb["id"] == kb_id:
                target = kb
            else:
                new_kbs.append(kb)
        if not target:
            raise ValueError(f"知识库 {kb_id} 不存在")

        # 1. 清理关联文档的向量数据
        from app.core.vector_store import VectorStore
        removed_chunks = VectorStore.delete_by_kb(kb_id)

        # 2. 清理关联文档的图谱节点
        from app.services.document_service import _documents
        from app.services.knowledge_graph import KnowledgeGraphService
        kb_docs = [d for d in _documents.values() if getattr(d, "knowledge_base_id", "default") == kb_id]
        for d in kb_docs:
            try:
                kg = KnowledgeGraphService(knowledge_base_id=kb_id)
                kg.delete_by_doc_id(d.id)
                kg._save_graph()
            except Exception as e:
                logger.warning(f"[KB] 清理文档 {d.id} 图谱失败: {e}")

        # 3. 清理 KB 物理图谱文件
        graph_file = _graph_file_for_kb(kb_id)
        if graph_file.exists():
            try:
                graph_file.unlink()
            except Exception as e:
                logger.warning(f"[KB] 删除图谱文件失败: {e}")

        # 4. 清理 KB 内存中的文档记录
        for d in kb_docs:
            _documents.pop(d.id, None)

        # 5. 持久化文档列表
        from app.services.document_service import save_documents
        save_documents()

        # 6. 移除 KB 元数据
        _save_kbs(new_kbs)
        _log_kb_op("DELETE", kb_id, f"name={target['name']} removed_chunks={removed_chunks} removed_docs={len(kb_docs)}")
        target["removed_chunks"] = removed_chunks
        target["removed_docs"] = len(kb_docs)
        return target

    @staticmethod
    def update_doc_count(kb_id: str, delta: int = 1):
        """更新知识库文档计数"""
        kbs = _load_kbs()
        for kb in kbs:
            if kb["id"] == kb_id:
                kb["doc_count"] = kb.get("doc_count", 0) + delta
                break
        _save_kbs(kbs)

    @staticmethod
    def migrate_document(doc_id: str, from_kb: str, to_kb: str) -> dict:
        """跨库迁移文档

        1. 更新文档的 knowledge_base_id
        2. 从源库图谱移除相关节点
        3. 在目标库图谱重建
        4. 记录迁移日志
        """
        from app.services.document_service import _documents

        doc = _documents.get(doc_id)
        if not doc:
            raise ValueError(f"文档 {doc_id} 不存在")

        old_kb = doc.knowledge_base_id
        if old_kb != from_kb:
            raise ValueError(f"文档不在源知识库中（期望 {from_kb}，实际 {old_kb}）")

        # 1. 从源库图谱删除文档节点
        from app.services.knowledge_graph import KnowledgeGraphService
        kg_src = KnowledgeGraphService(knowledge_base_id=from_kb)
        kg_src.delete_by_doc_id(doc_id)
        kg_src._save_graph()

        # 2. 更新文档的 kb_id
        doc.knowledge_base_id = to_kb
        KnowledgeBaseService.update_doc_count(from_kb, -1)
        KnowledgeBaseService.update_doc_count(to_kb, 1)

        # 3. 在目标库图谱重建
        kg_dst = KnowledgeGraphService(knowledge_base_id=to_kb)
        result = kg_dst.build_from_document(doc_id, doc.title, doc.content)

        _log_kb_op("MIGRATE", f"{from_kb}->{to_kb}",
                   f"doc={doc_id} title={doc.title} nodes={result.get('nodes_added', 0)}")

        return {
            "doc_id": doc_id,
            "from_kb": from_kb,
            "to_kb": to_kb,
            "title": doc.title,
            "graph_result": result,
        }

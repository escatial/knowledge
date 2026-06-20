"""系统 FAQ 文档管理 —— Task Z v2（Chroma 驱动）

设计变更（Task Z v2）：
- 0 硬编码：所有 FAQ 内容入库 Chroma（与正式文档统一）
- 默认内容：通过 system_faq_importer.DEFAULT_FAQ_SEEDS 在启动时入库
- 运行时扩展：通过 system_faq_importer.add_external_faq() 动态添加
- 异常安全：检索失败时记录 warning，返回空 list

迁移记录：
- v1：原 SYSTEM_FAQ_DOCS 硬编码在代码里（已删除）
- v2：JSON 文件 + KnowledgeProvider（违反 Chroma 架构意图，已废弃）
- v3 (当前)：Chroma 向量库 + system_faq_importer
"""
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


def get_system_faq_docs(kb_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """根据 kb_id 从 Chroma 加载 system_faq 文档

    加载策略：
      1. 遍历 DEFAULT_FAQ_SEEDS 列表，逐个从 Chroma 读 content
      2. 转换格式为 system_faq 内部 dict 格式

    返回:
        list of {id, title, content, score}；检索失败时返回空 list
    """
    try:
        from app.core.vector_store import VectorStore
        from app.core.system_faq_importer import (
            DEFAULT_FAQ_SEEDS, SYSTEM_FAQ_PREFIX, SYSTEM_FAQ_SOURCE
        )

        # 任务 Z：遍历所有 seed，从 Chroma 读 content
        # 这样默认 system_faq 列表（DEFAULT_FAQ_SEEDS）是开发期内容
        # 运营/用户可调用 add_external_faq() 动态添加新的
        # 老 list_all_chunks 接口不能按 metadata 过滤，所以用 list_chunks_by_doc 逐个读
        faqs = []
        for seed in DEFAULT_FAQ_SEEDS:
            doc_id = seed["id"]
            chunks = VectorStore.list_chunks_by_doc(doc_id)
            if chunks:
                # 找到对应 metadata
                title = seed["title"]
                for ck in chunks:
                    meta = ck.get("metadata", {}) or {}
                    if "title" in meta:
                        title = meta["title"]
                faqs.append({
                    "id": doc_id,
                    "title": title,
                    "content": chunks[0].get("content", seed["content"]),
                    "score": 1.0,
                })
            else:
                # 该 seed 还未入库（可能在初始化之前）→ 跳过
                logger.debug(f"[system_faq] {doc_id} 暂未入库，跳过")

        logger.info(f"[system_faq] FAQ 加载 | kb_id={kb_id} | count={len(faqs)} | source=chroma")
        return faqs

    except Exception as e:
        logger.error(f"[system_faq] FAQ 加载失败 | kb_id={kb_id} | {e}", exc_info=True)
        return []


# 兼容旧接口的辅助函数
def _find_kb(kb_id: str) -> Optional[Dict[str, Any]]:
    """从 knowledge_bases.json 查找 KB（兼容旧接口）"""
    try:
        from app.services.knowledge_base import _load_kbs
        for kb in _load_kbs():
            if kb.get("id") == kb_id:
                return kb
    except Exception as e:
        logger.warning(f"[system_faq] 查找 KB 失败: {e}")
    return None


def _infer_kb_categories(kb_id: Optional[str]) -> List[str]:
    """从 documents 中提取 KB 实际包含的分类"""
    try:
        from app.services.document_service import _documents
        if kb_id and kb_id not in ("default", "all", None):
            cats = {d.category for d in _documents.values()
                    if getattr(d, "knowledge_base_id", "default") == kb_id}
        else:
            cats = {d.category for d in _documents.values()}
        return sorted(cats)
    except Exception as e:
        logger.warning(f"[system_faq] 推断 KB 分类失败: {e}")
        return []

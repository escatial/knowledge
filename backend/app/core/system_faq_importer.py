"""System FAQ 入库脚本（Chroma 驱动）

任务 Z v2：把 system_faq 内容入库 Chroma（与正式文档统一）
- 用 source="system_faq" 标识
- 用 doc_id 前缀 "__sfq__" 隔离主库
- 启动时自动调用 init_system_faq() 初始化
- 运营/用户可通过 _import_external_faqs() 动态导入新 FAQ 内容
"""
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# ============================================================
# 标识常量
# ============================================================
SYSTEM_FAQ_PREFIX = "__sfq__"  # doc_id 前缀，避免与正式 doc 冲突
SYSTEM_FAQ_CATEGORY = "系统内置"
SYSTEM_FAQ_SOURCE = "system_faq"


# ============================================================
# 默认 system_faq 素材（开发期临时内容，可被外部素材覆盖）
# ============================================================
# 任务 Z：开发期 system_faq 素材以代码常量形式定义
# 这样可以保证：
# 1. 0 外部硬编码（用户要传知识素材时走 add_external_faq()）
# 2. 默认内容随项目代码一起发布（git tracked）
# 3. 上线正式知识素材后，可清空此列表，系统按 Chroma 内容运行
DEFAULT_FAQ_SEEDS: List[Dict[str, Any]] = [
    {
        "id": f"{SYSTEM_FAQ_PREFIX}kb_overview",
        "title": "知识库介绍",
        "content": (
            "本知识库是一个支持检索增强生成（RAG）、知识图谱与多模态管理的私有知识平台。\n"
            "知识库的核心能力包括：\n"
            "1. 文档入库：支持多种常见文档格式，上传时按配置的策略自动分块、向量化并入库。\n"
            "2. 知识图谱：自动从文档中抽取实体与关系，支持实体名搜索、节点详情查看与可视化浏览。\n"
            "3. 混合检索：提供向量、图谱、关键词三种检索通道，查询时并行召回并按相关度融合排序。\n"
            "4. 智能问答：基于入库内容给出回答，每条回答附带引用来源，可查看原文与相关度。\n"
            "5. 分块与多分类：支持多种分块策略，并按分类组织文档，便于按主题检索。"
        ),
    },
    {
        "id": f"{SYSTEM_FAQ_PREFIX}kb_usage",
        "title": "知识库使用方式",
        "content": (
            "知识库的使用方式：\n"
            "1. 在「文档管理」页面上传资料，新文档会自动入库并参与后续检索。\n"
            "2. 在「混合检索」页用关键词搜索，可同时命中向量、图谱、关键词三路结果。\n"
            "3. 在「智能问答」页用自然语言提问，知识库会基于内容给出带引用的答案。\n"
            "4. 在「知识图谱」页浏览知识库中的实体与关系网络。\n"
            "5. 在「系统设置」页可调整 LLM、Embedding 模型与分块策略。\n"
            "\n"
            "如需查询知识库内具体技术主题（如某个概念、框架、方法的定义与原理），"
            "请直接以该主题作为问题提问，系统会基于实际入库的文档内容给出回答。"
        ),
    },
]


def init_system_faq(force: bool = False) -> int:
    """初始化 system_faq 文档入库

    启动时自动调用：
    - 如果 system_faq 文档已存在且 force=False，跳过
    - 否则把 DEFAULT_FAQ_SEEDS 写入 Chroma

    返回: 实际入库的文档数
    """
    try:
        from app.core.vector_store import VectorStore
    except ImportError as e:
        logger.error(f"[system_faq_importer] 导入 VectorStore 失败: {e}")
        return 0

    if not force:
        # 检查 system_faq 是否已存在（用 count_by_doc_id 检查第一个 seed）
        first_seed_id = DEFAULT_FAQ_SEEDS[0]["id"] if DEFAULT_FAQ_SEEDS else None
        if first_seed_id and VectorStore.count_by_doc_id(first_seed_id) > 0:
            logger.info(f"[system_faq_importer] system_faq 已存在，跳过初始化")
            return 0

    count = 0
    for faq in DEFAULT_FAQ_SEEDS:
        try:
            # 单条内容作为一个 chunk 入库
            VectorStore.add_document(
                doc_id=faq["id"],
                chunks=[faq["content"]],
                metadata=[{
                    "doc_id": faq["id"],
                    "title": faq["title"],
                    "category": SYSTEM_FAQ_CATEGORY,
                    "knowledge_base_id": "__system_faq__",
                    "source": SYSTEM_FAQ_SOURCE,
                }],
            )
            count += 1
            logger.info(f"[system_faq_importer] system_faq 入库 | {faq['title']}")
        except Exception as e:
            logger.error(f"[system_faq_importer] 入库失败 | {faq['title']} | {e}", exc_info=True)

    logger.info(f"[system_faq_importer] 初始化完成 | 共入库 {count} 条 system_faq")
    return count


def add_external_faq(faq_id: str, title: str, content: str, knowledge_base_id: Optional[str] = None) -> bool:
    """动态添加外部 FAQ 文档（运行时 API）

    用于：
    - 运营/管理员通过管理界面添加新的 system_faq 文档
    - 集成第三方知识源时把内容入库

    参数:
        faq_id: 文档 ID（建议加前缀避免冲突，如 'medical_kb_overview'）
        title: 文档标题
        content: 文档内容
        knowledge_base_id: KB ID（None/空使用 default）

    返回: True=成功
    """
    try:
        from app.core.vector_store import VectorStore
    except ImportError as e:
        logger.error(f"[system_faq_importer] 导入 VectorStore 失败: {e}")
        return False

    # 强制使用 system_faq 前缀
    if not faq_id.startswith(SYSTEM_FAQ_PREFIX):
        faq_id = f"{SYSTEM_FAQ_PREFIX}{faq_id}"

    kb_id = knowledge_base_id or "__system_faq__"
    try:
        VectorStore.add_document(
            doc_id=faq_id,
            chunks=[content],
            metadata=[{
                "doc_id": faq_id,
                "title": title,
                "category": SYSTEM_FAQ_CATEGORY,
                "knowledge_base_id": kb_id,
                "source": SYSTEM_FAQ_SOURCE,
            }],
        )
        logger.info(f"[system_faq_importer] 动态入库 | doc_id={faq_id} | title={title}")
        return True
    except Exception as e:
        logger.error(f"[system_faq_importer] 动态入库失败 | {faq_id} | {e}", exc_info=True)
        return False

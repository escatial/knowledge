"""动态 UI 模板接入层（Task Z 重新定位）

任务 Z v2：明确职责边界
- 知识内容（FAQ、文档、向量化素材）走 Chroma 向量库（与其他文档统一）
- 本模块只负责**响应模板**（如"未找到"占位文案、错误提示等 UI 文案）
- 这是配置类资源，适合 JSON 文件；不是知识内容

目录结构（简化后）：
  backend/data/knowledge/
    fallback/
      response_templates.json   # 兜底响应模板（UI 文案，不是知识）

未来扩展（如需加载更多配置）：
  backend/data/knowledge/
    fallback/response_templates.json
    prompts/                   # prompt 模板（可选）
    ui/                        # UI 字符串/i18n（可选）
"""
import json
import logging
import threading
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ============================================================
# 路径配置
# ============================================================
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_KNOWLEDGE_DIR = _BACKEND_DIR / "data" / "knowledge"
_FALLBACK_DIR = _KNOWLEDGE_DIR / "fallback"

# i18n 默认值：连 JSON 都加载失败时使用（final 兜底）
I18N_DEFAULTS = {
    "fallback_no_definition": "抱歉，知识库中**没有关于「{question}」的直接概念定义文档**。\n\n但是检索到 {count} 条相关资料（多为代码示例）：\n{titles}\n\n⚠️ **建议**：\n1. 如需了解「{question}」的概念定义/原理介绍，请上传相关介绍文档\n2. 您可以换个更具体的问题\n3. 点击下方引用卡可查看代码示例原文",
    "fallback_no_match": "抱歉，知识库中暂未找到与「{question}」相关的内容。建议您换个问法，或上传包含相关主题的文档。",
    "fallback_llm_unavailable": "抱歉，模型暂时无法生成回答，请稍后重试。",
}


class KnowledgeProvider:
    """动态 UI 模板接入层（单例）

    重要：知识内容（FAQ/文档）已迁回 Chroma 向量库
    本类只管 UI 响应模板（响应文案、错误提示等）
    """

    _instance: Optional["KnowledgeProvider"] = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._template_cache: Dict[str, str] = {}
        logger.info(f"[KnowledgeProvider] 初始化 | 根目录={_KNOWLEDGE_DIR}")

    # ============================================================
    # 1. 响应模板加载
    # ============================================================
    def get_template(self, name: str, **kwargs) -> str:
        """获取 UI 响应模板

        参数:
            name: 模板名（对应 response_templates.json 中的 key）
            **kwargs: 模板占位符（如 {question}, {count}, {titles}）

        返回:
            渲染后的字符串；模板不存在时返回 i18n 默认值
        """
        if name not in self._template_cache:
            templates = self._load_json_file(_FALLBACK_DIR / "response_templates.json", "templates")
            if templates and name in templates:
                self._template_cache[name] = templates[name]
            else:
                # i18n 兜底
                self._template_cache[name] = I18N_DEFAULTS.get(
                    name, "抱歉，知识库中暂未找到与「{question}」相关的内容。"
                )
                logger.warning(f"[KnowledgeProvider] 模板 {name!r} 不存在，使用 i18n 默认值")

        template = self._template_cache[name]
        try:
            return template.format(**kwargs)
        except KeyError as e:
            logger.warning(f"[KnowledgeProvider] 模板 {name!r} 缺少占位符 {e}，原始返回")
            return template

    def clear_template_cache(self):
        """清除模板缓存（热更新用）"""
        self._template_cache.clear()
        logger.info("[KnowledgeProvider] 模板缓存已清除")

    # ============================================================
    # 2. 内部工具
    # ============================================================
    @staticmethod
    def _load_json_file(path: Path, key: Optional[str] = None):
        """加载 JSON 文件（带异常处理）"""
        if not path.exists():
            logger.debug(f"[KnowledgeProvider] 素材文件不存在: {path}")
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if key is not None:
                if not isinstance(data, dict) or key not in data:
                    logger.warning(f"[KnowledgeProvider] {path} 缺少顶层 key {key!r}")
                    return None
                return data[key]
            return data
        except json.JSONDecodeError as e:
            logger.error(f"[KnowledgeProvider] JSON 解析失败: {path} | {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"[KnowledgeProvider] 文件读取失败: {path} | {e}", exc_info=True)
            return None


# ============================================================
# 全局访问入口
# ============================================================
_provider_singleton: Optional[KnowledgeProvider] = None


def get_knowledge_provider() -> KnowledgeProvider:
    """获取 KnowledgeProvider 单例"""
    global _provider_singleton
    if _provider_singleton is None:
        _provider_singleton = KnowledgeProvider()
    return _provider_singleton

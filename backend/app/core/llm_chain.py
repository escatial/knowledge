"""
LLM 服务封装 - 基于 LangChain 原生组件
支持多模型动态切换、流式输出、异常处理
"""
import logging
from typing import Iterator, Optional, Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.callbacks import StreamingStdOutCallbackHandler

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMConfig:
    """LLM 配置解析器"""

    @staticmethod
    def resolve(model: Optional[str] = None) -> dict[str, str]:
        """根据模型名称解析 API 配置"""
        model_lower = (model or "").lower()

        if "deepseek" in model_lower:
            return {
                "api_key": settings.DEEPSEEK_API_KEY,
                "base_url": settings.DEEPSEEK_BASE_URL,
                "model_name": model or settings.DEEPSEEK_MODEL,
            }

        # 默认 MiniMax
        return {
            "api_key": settings.OPENAI_API_KEY,
            "base_url": settings.OPENAI_BASE_URL,
            "model_name": model or settings.OPENAI_MODEL,
        }


class LLMChainService:
    """
    基于 LangChain ChatOpenAI 的 LLM 服务
    支持：多模型切换、流式输出、结构化异常处理
    """

    @staticmethod
    def get_llm(
        model: Optional[str] = None,
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> ChatOpenAI:
        """
        获取 LangChain ChatOpenAI 实例

        Args:
            model: 模型名称，None 则使用默认
            stream: 是否启用流式输出
            temperature: 温度参数
            max_tokens: 最大输出 token 数

        Returns:
            ChatOpenAI 实例
        """
        config = LLMConfig.resolve(model)

        callbacks = [StreamingStdOutCallbackHandler()] if stream else None

        try:
            llm = ChatOpenAI(
                model=config["model_name"],
                api_key=config["api_key"],
                base_url=config["base_url"],
                temperature=temperature,
                max_tokens=max_tokens,
                streaming=stream,
                callbacks=callbacks,
                timeout=60,
            )
            logger.info(
                f"[LLM] 初始化成功 | model={config['model_name']} | stream={stream}"
            )
            return llm
        except Exception as e:
            logger.error(f"[LLM] 初始化失败: {e}")
            raise RuntimeError(f"LLM 初始化失败: {e}") from e

    @staticmethod
    def chat(
        messages: list[dict[str, str]],
        stream: bool = False,
        model: Optional[str] = None,
    ) -> str | Iterator[str]:
        """
        对话接口 - 兼容原有调用方式

        Args:
            messages: OpenAI 格式的消息列表 [{"role": "user", "content": "..."}]
            stream: 是否流式输出
            model: 指定模型

        Returns:
            非流式: str 回答内容
            流式: Iterator[str] 逐字符生成器
        """
        try:
            llm = LLMChainService.get_llm(model=model, stream=stream)

            # 转换消息格式
            lc_messages = []
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "system":
                    lc_messages.append(SystemMessage(content=content))
                elif role == "assistant":
                    lc_messages.append(AIMessage(content=content))
                else:
                    lc_messages.append(HumanMessage(content=content))

            logger.info(f"[LLM] 调用 | messages={len(lc_messages)} | stream={stream}")

            if stream:
                return LLMChainService._stream_response(llm, lc_messages)

            # 任务 N：调用失败时重试 1 次（网络抖动场景）
            try:
                response = llm.invoke(lc_messages)
                return response.content
            except Exception as first_err:
                logger.warning(f"[LLM] 首次调用失败，重试 1 次: {first_err}")
                try:
                    response = llm.invoke(lc_messages)
                    logger.info("[LLM] 重试成功")
                    return response.content
                except Exception as retry_err:
                    logger.error(f"[LLM] 重试仍失败: {retry_err}")
                    # 任务 N：返回带前缀的明确错误标识（前端可识别，不触发"未找到"截断）
                    return f"[LLM_ERROR_RETRY_FAILED] {str(retry_err)}"

        except Exception as e:
            logger.error(f"[LLM] 调用失败: {e}")
            return f"[LLM_ERROR] {str(e)}"

    @staticmethod
    def _stream_response(llm: ChatOpenAI, messages: list) -> Iterator[str]:
        """流式响应生成器"""
        import re as _re_stream
        # 任务 P3-7 修复：流式输出也清洗占位符（避免 [object Object] 等污染）
        _CHUNK_PATTERNS = [
            (r"\[object\s+\w+\]", ""),
            (r"<undefined>", ""),
            (r"<null>", ""),
            (r"<empty>", ""),
        ]
        def _clean(text: str) -> str:
            for p, r in _CHUNK_PATTERNS:
                text = _re_stream.sub(p, r, text)
            return text
        try:
            for chunk in llm.stream(messages):
                if chunk.content:
                    cleaned = _clean(chunk.content)
                    if cleaned:
                        yield cleaned
        except Exception as e:
            logger.error(f"[LLM] 流式输出中断: {e}")
            yield f"[LLM 流式输出中断: {str(e)}]"

    @staticmethod
    def extract_entities(text: str, model: Optional[str] = None) -> dict:
        """基于 LLM 的实体关系抽取"""
        prompt = f"""从以下文本中提取实体和关系，返回 JSON 格式。

要求：
1. 实体类型包括：人物、组织、地点、概念、技术、产品、事件
2. 关系类型包括：属于、创建、使用、位于、参与、相关、包含
3. 只提取重要的实体和关系

文本：
{text[:3000]}

返回格式：
{{
  "entities": [
    {{"id": "e1", "name": "实体名称", "type": "人物|组织|地点|概念|技术|产品|事件", "description": "简要描述"}}
  ],
  "relations": [
    {{"source": "e1", "target": "e2", "type": "关系类型", "description": "关系描述"}}
  ]
}}
"""
        try:
            llm = LLMChainService.get_llm(model=model, stream=False)
            messages = [
                SystemMessage(
                    content="你是一个知识图谱构建专家，擅长从文本中提取实体和关系。只返回 JSON，不要其他内容。"
                ),
                HumanMessage(content=prompt),
            ]
            response = llm.invoke(messages)

            import json
            import re

            json_match = re.search(r"\{.*\}", response.content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception as e:
            logger.error(f"[LLM] 实体抽取失败: {e}")

        return {"entities": [], "relations": []}

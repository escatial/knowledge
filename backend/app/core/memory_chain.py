"""
对话记忆管理 - 基于 LangChain 原生组件
使用 ConversationBufferWindowMemory + 追问检测
"""
import logging
import re
from typing import Optional

from langchain.memory import ConversationBufferWindowMemory
from langchain_core.messages import HumanMessage, AIMessage

logger = logging.getLogger(__name__)


class FollowUpDetector:

    # 任务 L：查询同义词词典（解决 BGE 短词召回低的问题）
    # 键: 用户可能输入的查询；值: 扩展同义词列表
    _QUERY_SYNONYMS: dict[str, list[str]] = {
        # Agent
        "agent": ["智能体", "代理", "智能体框架", "agent 系统", "LLM Agent"],
        "智能体": ["agent", "LLM agent", "代理"],
        "Agent化RAG": ["Agent化的RAG", "agent rag", "智能体 RAG"],
        "Agent化": ["agent", "智能体", "agentic"],
        # RAG
        "RAG": ["检索增强生成", "Retrieval-Augmented Generation", "RAG 技术"],
        "检索增强生成": ["RAG", "Retrieval-Augmented Generation"],
        # LLM
        "LLM": ["大语言模型", "大模型", "Large Language Model"],
        "大语言模型": ["LLM", "大模型"],
        "大模型": ["LLM", "大语言模型"],
        # LangChain / LangGraph / MCP
        "LangGraph": ["LangGraph 框架", "langgraph"],
        "LangChain": ["LangChain 框架", "langchain"],
        "MCP": ["Model Context Protocol", "MCP 协议", "ModelContextProtocol"],
    }

    @classmethod
    def expand_with_synonyms(cls, query: str) -> str:
        """任务 L：用同义词词典扩展短查询 → 提高向量检索召回率

        任务 X 修复：只对纯短查询（≤ 10 字符）做扩展，不再对"含关键词的复合 query"扩展。

        问题案例：query="RAG 的核心流程是什么?"，原本会扩展为
        "RAG 的核心流程是什么? | 检索增强生成 | Retrieval-Augmented Generation | RAG 技术"
        这种拼接会严重稀释 embedding 语义，导致 RAG 检索结果跑偏（返回 LangChain/LangGraph 等无关文档），
        LLM 进而输出"知识库中暂未找到"。

        修复：只对完全由同义词词典 key 构成的短查询做扩展，长 query 一律不扩展。
        """
        q_stripped = query.strip()
        if not q_stripped:
            return query

        # 1. 只在 query 极短（≤ 10 字符）且完全命中词典 key 时扩展
        if len(q_stripped) <= 10 and q_stripped in cls._QUERY_SYNONYMS:
            synonyms = cls._QUERY_SYNONYMS[q_stripped]
            return f"{q_stripped} | {' | '.join(synonyms)}"

        # 2. 其他情况一律不扩展（避免污染长 query）
        return query

    """
    追问检测器 - 结合规则 + 语义判断
    """

    FOLLOW_UP_PATTERNS = [
        r"具体的呢?",
        r"具体.*?(呢|呢？|说说|讲讲|呢\?|怎么|为啥|为什么|如何)",
        r"详细说说?",
        r"详细点",
        r"再说说",
        r"为什么",
        r"什么意思",
        r"举个例子",
        r"展开",
        r"深入",
        r"接着说",
        r"然后呢",
        r"还有呢",
        r"怎么说",
        r"怎么理解",
        r"如何操作",
        r"怎么做",
        r"步骤是什么",
    ]

    PRONOUN_PATTERNS = [
        r"[它他她这那]个?",
        r"[它他她这那]些?",
        r"[它他她这那]种?",
        r"上面",
        r"之前",
        r"刚才",
        r"上文",
    ]

    # 任务 5（质量整改）：当 query 命中这些"系统功能/独立问题"信号时，强制**不**视为追问
    # 即便有历史也不做主题拼接。优先级最高。
    NON_FOLLOWUP_OVERRIDE = [
        r"^(介绍|了解|认识).*?(知识库|系统|平台|工具|你|您)",
        r"^(什么是|啥是|啥是|啥叫)",
        r"^你(是什么|是谁|能做什么|有什么功能)",
        r"^(系统|平台|工具|知识库).*?(能做|可以|功能|能力)",
        r"^(帮助|help|使用教程|使用指南)$",
    ]

    @classmethod
    def is_follow_up(cls, query: str, history: list[dict]) -> bool:
        """判断是否为追问（修复后：短句不再被一刀切判定为追问）"""
        if not history:
            return False

        query_short = query.strip()

        # 任务 5（修复）：先做"非追问"覆盖——独立完整问题应直接跳过追问路径
        for pattern in cls.NON_FOLLOWUP_OVERRIDE:
            if re.search(pattern, query_short):
                return False

        has_pronoun = False
        for pattern in cls.PRONOUN_PATTERNS:
            if re.search(pattern, query_short):
                has_pronoun = True
                break

        # 短句 + 含指代词 → 追问（用 6 字符作为阈值更严格）
        if len(query_short) < 6 and has_pronoun:
            return True

        # 追问关键词
        for pattern in cls.FOLLOW_UP_PATTERNS:
            if re.search(pattern, query_short):
                return True

        # 含指代词 → 追问
        if has_pronoun:
            return True

        return False

    @classmethod
    def extract_topic(cls, history: list[dict]) -> str:
        """从历史对话中提取主题（修复：跳过"未找到"型回答、跳过太短/太泛的 user 消息）"""
        not_found_markers = [
            "暂未找到", "未找到", "没有找到", "知识库中暂未",
            "未提供", "抱歉", "没找到", "建议换个", "建议重新",
        ]
        for msg in reversed(history):
            if msg.get("role") != "user":
                continue
            content = (msg.get("content") or "").strip()
            if len(content) < 4:
                continue
            # 跳过主题词本身就含有"未找到"的用户问题（用户复读前序失败）
            if any(m in content for m in not_found_markers):
                continue
            # 太短或太泛的指令不作为主题
            if content in ("你好", "hi", "hello", "在吗", "帮助", "help"):
                continue
            return content
        return ""

    @classmethod
    def expand_query(cls, query: str, history: list[dict]) -> str:
        """如果是追问，用主题扩展检索查询（修复后：仅当 is_follow_up 为真时才扩展）

        任务 X 修复：原逻辑 f"{topic} {query}" 拼接污染检索 query
        （如 "Agent 是什么 具体而言呢？" —— "具体而言呢？"作为检索词毫无意义）
        新逻辑：用 LLM 智能重写 query，把追问改写为自包含的检索 query
        如果 LLM 调用失败，回退到原 topic + query
        """
        if not cls.is_follow_up(query, history):
            return query

        topic = cls.extract_topic(history)
        if not topic or topic == query:
            return query

        # 任务 X：用 LLM 智能重写
        rewritten = cls._llm_rewrite_followup(query, topic, history)
        if rewritten:
            return rewritten

        # 兜底：直接拼接（但用 LLM 重写优先）
        return f"{topic} {query}"

    @classmethod
    def _llm_rewrite_followup(cls, query: str, topic: str, history: list[dict]) -> str:
        """用 LLM 把追问改写为自包含检索 query

        输入：query="具体而言呢？", topic="Agent 是什么"
        输出：自包含检索词，例如 "Agent 的具体定义"

        失败时返回 None，调用方回退到原 topic 拼接
        """
        try:
            from app.core.llm_chain import LLMChainService
            from langchain_core.messages import SystemMessage, HumanMessage

            # 取最近 2 轮对话作为上下文
            recent_history = history[-4:] if history else []
            history_str = "\n".join(
                f"{m.get('role', 'unknown')}: {m.get('content', '')[:200]}"
                for m in recent_history
                if m.get('content')
            )

            prompt = (
                f"以下是用户与 AI 助手的最近对话：\n\n"
                f"{history_str}\n\n"
                f"用户最新问题：{query}\n\n"
                f"请把用户的最新问题改写为一个【自包含、适合检索】的查询。"
                f"要求：\n"
                f"1. 必须包含指代消解（把『它/这/这个』等指代词替换为具体主题）\n"
                f"2. 必须保留用户的核心问题\n"
                f"3. 不要加任何额外解释，只返回改写后的查询\n"
                f"4. 长度控制在 50 字以内\n"
                f"5. 如果用户问题已经自包含，直接原样返回\n\n"
                f"改写后的查询："
            )

            llm = LLMChainService.get_llm(stream=False, temperature=0.1)
            resp = llm.invoke([
                SystemMessage(content="你是查询改写助手，专门把追问改写为自包含检索词。"),
                HumanMessage(content=prompt),
            ])
            rewritten = (resp.content or "").strip()
            # 清理：去掉引号/前缀
            rewritten = rewritten.strip("「」『』'\"` ").strip()
            # 长度限制
            if 2 <= len(rewritten) <= 100:
                return rewritten
        except Exception as e:
            # LLM 调用失败，让调用方走兜底
            print(f"[FollowUpDetector] LLM rewrite failed: {e}")
        return None


class ChatMemoryChainManager:
    """
    对话记忆管理器 - 基于 LangChain ConversationBufferWindowMemory
    每个 session_id 对应一个独立的记忆实例
    """

    _instances: dict[str, ConversationBufferWindowMemory] = {}

    @classmethod
    def get_memory(cls, session_id: str, k: int = 6) -> ConversationBufferWindowMemory:
        """获取或创建指定会话的记忆实例"""
        if session_id not in cls._instances:
            cls._instances[session_id] = ConversationBufferWindowMemory(
                k=k,
                return_messages=True,
                memory_key="chat_history",
            )
            logger.info(f"[Memory] 创建新记忆实例 | session_id={session_id}")
        return cls._instances[session_id]

    @classmethod
    def delete_memory(cls, session_id: str):
        """删除指定会话的记忆实例"""
        if session_id in cls._instances:
            del cls._instances[session_id]
            logger.info(f"[Memory] 删除记忆实例 | session_id={session_id}")

    @classmethod
    def add_exchange(cls, session_id: str, query: str, answer: str):
        """记录一轮对话到记忆"""
        memory = cls.get_memory(session_id)
        memory.chat_memory.add_user_message(query)
        memory.chat_memory.add_ai_message(answer)
        logger.debug(f"[Memory] 记录对话 | session_id={session_id}")

    @classmethod
    def get_history(cls, session_id: str) -> list[dict]:
        """获取 OpenAI 格式的消息历史"""
        memory = cls.get_memory(session_id)
        messages = memory.load_memory_variables({})["chat_history"]

        result = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                result.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                result.append({"role": "assistant", "content": msg.content})
        return result

    @classmethod
    def sync_from_context(cls, session_id: str, context: list[dict]):
        """从前端传来的 context 同步历史到记忆（首次加载时）"""
        memory = cls.get_memory(session_id)

        # 如果记忆为空，同步前端历史
        if not memory.load_memory_variables({})["chat_history"] and context:
            for msg in context[-12:]:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role == "user":
                    memory.chat_memory.add_user_message(content)
                elif role == "assistant":
                    memory.chat_memory.add_ai_message(content)
            logger.info(f"[Memory] 同步历史 | session_id={session_id} | messages={len(context)}")

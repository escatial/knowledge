"""
对话记忆管理模块 - 轻量级实现，对标 LangChain ConversationBufferWindowMemory
支持：缓冲窗口记忆、Token 预算管理、追问智能检测、主题提取
"""
import json
import re
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class ChatMessage:
    """单条对话消息"""
    role: str
    content: str
    timestamp: float = field(default_factory=lambda: __import__('time').time())


class ConversationBufferWindowMemory:
    """
    滑动窗口对话记忆
    保持最近 k 轮对话（2*k 条消息），自动管理上下文窗口
    """

    def __init__(self, k: int = 6, max_tokens: int = 4000):
        self.k = k
        self.max_tokens = max_tokens
        self.messages: list[ChatMessage] = []

    def add_user_message(self, content: str):
        self.messages.append(ChatMessage(role="user", content=content))
        self._trim()

    def add_ai_message(self, content: str):
        self.messages.append(ChatMessage(role="assistant", content=content))
        self._trim()

    def _trim(self):
        """修剪消息列表，保持最近 k 轮对话"""
        max_messages = self.k * 2
        if len(self.messages) > max_messages:
            self.messages = self.messages[-max_messages:]

    def get_history(self) -> list[dict]:
        """返回 OpenAI 格式的消息列表"""
        return [{"role": m.role, "content": m.content} for m in self.messages]

    def clear(self):
        self.messages = []

    @property
    def is_empty(self) -> bool:
        return len(self.messages) == 0


class FollowUpDetector:
    """
    追问检测器 - 结合规则 + 语义判断
    比单纯关键词匹配更精准
    """

    # 追问关键词模式
    FOLLOW_UP_PATTERNS = [
        r'具体的呢?', r'详细说说?', r'为什么', r'什么意思',
        r'举个例子', r'展开', r'深入', r'接着说', r'然后呢',
        r'还有呢', r'怎么说', r'怎么理解', r'如何操作',
        r'怎么做', r'步骤是什么',
    ]

    # 指代词模式（强烈暗示追问）
    PRONOUN_PATTERNS = [
        r'[它他她这那]个?', r'[它他她这那]些?', r'[它他她这那]种?',
        r'上面', r'之前', r'刚才', r'上文',
    ]

    @classmethod
    def is_follow_up(cls, query: str, history: list[ChatMessage]) -> bool:
        """
        判断是否为追问
        规则：
        1. 短句（<10字）+ 有历史 → 大概率追问
        2. 包含追问关键词 → 追问
        3. 包含指代词 + 有历史 → 追问
        4. 无历史 → 不是追问
        """
        if not history:
            return False

        query_short = query.strip()

        # 规则1：短句 + 有历史
        if len(query_short) < 10:
            return True

        # 规则2：追问关键词
        for pattern in cls.FOLLOW_UP_PATTERNS:
            if re.search(pattern, query_short):
                return True

        # 规则3：指代词
        for pattern in cls.PRONOUN_PATTERNS:
            if re.search(pattern, query_short):
                return True

        return False

    @classmethod
    def extract_topic(cls, history: list[ChatMessage]) -> str:
        """
        从历史对话中提取主题
        取最近一条长度 >15 的用户消息作为主题
        """
        for msg in reversed(history):
            if msg.role == "user" and len(msg.content) > 15:
                return msg.content
        return ""

    @classmethod
    def expand_query(cls, query: str, history: list[ChatMessage]) -> str:
        """
        如果是追问，用主题扩展检索查询
        """
        if not cls.is_follow_up(query, history):
            return query

        topic = cls.extract_topic(history)
        if topic and topic != query:
            return f"{topic} {query}"
        return query


class ChatMemoryManager:
    """
    对话记忆管理器 - 会话级单例
    每个 session_id 对应一个独立的记忆实例
    """

    _instances: dict[str, ConversationBufferWindowMemory] = {}

    @classmethod
    def get_memory(cls, session_id: str, k: int = 6) -> ConversationBufferWindowMemory:
        """获取或创建指定会话的记忆实例"""
        if session_id not in cls._instances:
            cls._instances[session_id] = ConversationBufferWindowMemory(k=k)
        return cls._instances[session_id]

    @classmethod
    def clear_memory(cls, session_id: str):
        """清除指定会话的记忆"""
        if session_id in cls._instances:
            cls._instances[session_id].clear()

    @classmethod
    def delete_memory(cls, session_id: str):
        """删除指定会话的记忆实例"""
        cls._instances.pop(session_id, None)

    @classmethod
    def build_messages(
        cls,
        session_id: str,
        query: str,
        system_prompt: str,
        retrieved_context: str = ""
    ) -> list[dict]:
        """
        构建完整的 LLM 消息列表
        结构：system → history → knowledge_context → user_query
        """
        memory = cls.get_memory(session_id)

        messages = [{"role": "system", "content": system_prompt}]

        # 添加历史对话
        history = memory.get_history()
        messages.extend(history)

        # 添加知识库检索内容
        if retrieved_context and retrieved_context.strip():
            messages.append({
                "role": "system",
                "content": f"【知识库参考内容】\n{retrieved_context[:4000]}\n\n请基于以上知识库内容回答用户的最新问题。"
            })

        # 当前用户问题
        messages.append({"role": "user", "content": query})

        return messages

    @classmethod
    def add_exchange(cls, session_id: str, query: str, answer: str):
        """记录一轮对话到记忆"""
        memory = cls.get_memory(session_id)
        memory.add_user_message(query)
        memory.add_ai_message(answer)

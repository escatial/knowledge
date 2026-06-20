import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from threading import Lock
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# 思考/答案分离正则：DeepSeek-R1 / QwQ / o1 类模型会输出 <think>...</think>
THINK_PATTERN = re.compile(r"<think>(.*?)</think>", re.DOTALL)


def split_thinking_and_answer(text: str) -> tuple[str, str]:
    """把文本拆分为思考过程和最终答案"""
    if not text:
        return "", ""
    matches = THINK_PATTERN.findall(text)
    if not matches:
        return "", text
    thinking = "\n".join(matches).strip()
    answer = THINK_PATTERN.sub("", text).strip()
    return thinking, answer


@dataclass
class AITask:
    """单次问答任务的状态"""
    task_id: str
    question: str
    session_id: str
    status: str = "pending"  # pending / running / done / error
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    # 流式累积的原文（包含 <think> 标签）
    text: str = ""
    # v2：拆分后的思考过程
    thinking: str = ""
    # v2：拆分后的最终答案
    answer: str = ""
    # 元数据
    model: Optional[str] = None
    citations: List[dict] = field(default_factory=list)
    confidence: float = 0.0
    # 错误信息
    error: Optional[str] = None
    # 引用列表
    sources: List[str] = field(default_factory=list)
    # v2：检索时使用的分类筛选
    selected_categories: List[str] = field(default_factory=list)
    # 任务 Z v3：检索到的原始文档内容（page_content）
    # 供兜底改写时调用 LLM 重新生成
    context_docs: List[dict] = field(default_factory=list)


class AITaskManager:
    """全局任务管理器（线程安全）"""

    def __init__(self):
        self._tasks: Dict[str, AITask] = {}
        self._lock = Lock()
        self._max_history_per_session = 50

    def create(
        self,
        question: str,
        session_id: str,
        model: Optional[str] = None,
        selected_categories: Optional[List[str]] = None,
    ) -> AITask:
        task = AITask(
            task_id=str(uuid.uuid4()),
            question=question,
            session_id=session_id,
            model=model,
            selected_categories=selected_categories or [],
        )
        with self._lock:
            self._tasks[task.task_id] = task
            self._cleanup_old(session_id)
        logger.info(
            f"[TaskMgr] 创建任务 | task_id={task.task_id} | session={session_id} | "
            f"cats={selected_categories}"
        )
        return task

    def get(self, task_id: str) -> Optional[AITask]:
        with self._lock:
            return self._tasks.get(task_id)

    def update(self, task_id: str, **kwargs):
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            for k, v in kwargs.items():
                if hasattr(task, k):
                    setattr(task, k, v)
            task.updated_at = time.time()

    def append_text(self, task_id: str, delta: str):
        """追加 token 并实时拆分 thinking/answer"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task.text += delta
            task.thinking, task.answer = split_thinking_and_answer(task.text)
            task.updated_at = time.time()

    def replace_text(self, task_id: str, new_text: str):
        """任务 1.3：替换累积 text（用于引用标注对齐）"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task.text = new_text
            task.thinking, task.answer = split_thinking_and_answer(new_text)
            task.updated_at = time.time()

    def list_by_session(self, session_id: str) -> List[AITask]:
        with self._lock:
            return [t for t in self._tasks.values() if t.session_id == session_id]

    def delete(self, task_id: str):
        with self._lock:
            self._tasks.pop(task_id, None)

    def _cleanup_old(self, session_id: str):
        same_session = [t for t in self._tasks.values() if t.session_id == session_id]
        if len(same_session) <= self._max_history_per_session:
            return
        same_session.sort(key=lambda t: t.created_at)
        to_delete = same_session[: len(same_session) - self._max_history_per_session]
        for t in to_delete:
            self._tasks.pop(t.task_id, None)
        logger.debug(f"[TaskMgr] 清理旧任务 | session={session_id} | removed={len(to_delete)}")


_task_manager = AITaskManager()


def get_task_manager() -> AITaskManager:
    return _task_manager

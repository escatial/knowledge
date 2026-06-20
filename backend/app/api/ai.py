"""
AI 问答接口 - 全部走 RAGChainService（中心化）

所有端点（/ask、/ask/stream、/ask/async）均通过 RAGChainService 调用：
- /ask              → RAGChainService.ask()             同步
- /ask/stream       → RAGChainService.stream_ask()      SSE 流式
- /ask/async        → 后台任务模式，立即返回 task_id
- /tasks/{task_id}  → 任务状态查询（轮询）
- /ask/clear        → ChatMemoryChainManager.delete_memory()
- /meta-summary     → 任务 1：知识库元数据清单（绕过 RAG 检索）

不允许在路由层直接拼装 Prompt 或调用 LLM。
"""
import asyncio
import json
import logging
import re
import threading
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.core.llm_chain import LLMChainService
from app.core.rag_chain import RAGChainService
from app.core.memory_chain import ChatMemoryChainManager, FollowUpDetector
from app.core.ai_tasks import get_task_manager
from app.services.document_service import _documents
from app.core.vector_store import VectorStore

router = APIRouter()
logger = logging.getLogger(__name__)


# 任务 1.3：引用标注字符集（圈数字 1~20）
_CITATION_LABELS = [
    "①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩",
    "⑪", "⑫", "⑬", "⑭", "⑮", "⑯", "⑰", "⑱", "⑲", "⑳",
]

# 用于匹配"圈数字 1-50"（Unicode 0x2460-0x2473）的备用范围（emoji 形式）
_CITATION_REGEX = re.compile(r"[\u2460-\u2473]")  # ① ② ... ㊳

# 任务 X：剥离 LLM 输出的"引用来源/置信度评估"尾巴（前端已独立渲染）
# 任务 W 修复：要求关键词必须以独立段落/标题形式出现（前面必须有换行）
# 防止误伤句子中间的"引用来源"等词（如："每条回答都会附引用来源，可点击..."）
_TAIL_PATTERNS = [
    # 关键修复：必须以换行起始（独立段落），且关键词后紧跟冒号+换行
    re.compile(r'\n\s*(?:\*\*|##+)?\s*引用来源\s*[:：]\s*\n[\s\S]*$', re.MULTILINE),
    re.compile(r'\n\s*(?:\*\*|##+)?\s*引用列表\s*[:：]\s*\n[\s\S]*$', re.MULTILINE),
    re.compile(r'\n\s*(?:\*\*|##+)?\s*参考资料\s*[:：]\s*\n[\s\S]*$', re.MULTILINE),
    re.compile(r'\n\s*(?:\*\*|##+)?\s*置信度评估\s*[:：]\s*\n[\s\S]*$', re.MULTILINE),
    re.compile(r'\n\s*(?:\*\*|##+)?\s*置信度\s*[:：]\s*\n[\s\S]*$', re.MULTILINE),
    re.compile(r'\n\s*(?:\*\*|##+)?\s*回答总结\s*[:：]\s*\n[\s\S]*$', re.MULTILINE),
    re.compile(r'\n\s*(?:\*\*|##+)?\s*总结\s*[:：]\s*\n[\s\S]*$', re.MULTILINE),
    re.compile(r'\n-+\s*$'),  # 末尾的 markdown 分隔线
]


def _strip_llm_tails(answer: str) -> str:
    """任务 X：剥离 LLM 末尾自加的引用/置信度/总结段落

    系统已独立渲染这些模块，LLM 重复输出会破坏排版

    任务 W 修复：要求这些关键词必须以独立段落/标题出现
    """
    text = answer
    for pat in _TAIL_PATTERNS:
        text = pat.sub('', text)
    return text.rstrip()


# 任务 W：剥离 DeepSeek/Qwen 等模型的 思考过程标签
# 必须在最早期剥离，否则 _align_citations 会把 ① 等当成正文内容里的标号
_THINK_BLOCK_RE = re.compile(r'<\s*think\s*>[\s\S]*?<\s*/\s*think\s*>', re.IGNORECASE)
_THINK_OPEN_RE = re.compile(r'<\s*think\s*>', re.IGNORECASE)
_THINK_CLOSE_RE = re.compile(r'<\s*/\s*think\s*>', re.IGNORECASE)


def _strip_think_blocks(answer: str) -> str:
    """任务 W：剥离 LLM 的 思考过程

    某些模型（DeepSeek/QwQ/Qwen3 等）会输出 思考过程 块，
    该块不应暴露给最终用户（前端只渲染答案正文）。

    任务 X 修复：只有当 answer 同时包含【开启标签】和【闭合标签】时才剥离。
    原因：流式输出被截断时，LLM 可能只输出 <think> 而没有 </think>，
    此时若盲目截到 <think> 之前会丢掉全部 answer。
    """
    if not answer:
        return answer
    has_open = _THINK_OPEN_RE.search(answer) is not None
    has_close = _THINK_CLOSE_RE.search(answer) is not None
    # 1) 闭合的 思考过程...思考过程结束 整段剥离
    if has_open and has_close:
        cleaned = _THINK_BLOCK_RE.sub('', answer).strip()
        # 防御性：极端情况（异常闭合顺序）下，若还有残留开启标签
        if _THINK_OPEN_RE.search(cleaned):
            cleaned = _THINK_OPEN_RE.split(cleaned)[0].strip()
        return cleaned
    # 2) 没有同时具备 <think> 和 </think> → 保留原样，避免误删
    return answer.strip()

# 任务 1.3：把 LLM 生成的引用标号与真实 citations 数量严格对齐
def _align_citations(answer: str, citations: list) -> str:
    """任务 1.3：引用标注与来源一一对应绑定

    规则：
    0. 先剥离 LLM 末尾自加的"引用来源/置信度评估"段落
    1. 按出现顺序把所有 ① 标号重新映射为 ① ② ③...（处理 LLM 重复编号）
    2. 重排后数量 = citations 数：不足则补齐，过多则删除
    3. 标号最大只到 ⑳（20 条）
    """
    # 0. 剥离尾巴 + 任务 W：剥离 DeepSeek/Qwen 等的 思考过程 块
    answer = _strip_think_blocks(answer)
    answer = _strip_llm_tails(answer)

    if not citations:
        # 没有 citations → 清空所有标号
        return _CITATION_REGEX.sub("", answer)

    target_count = min(len(citations), len(_CITATION_LABELS))

    # 1. 重新编号：按出现顺序把 unicode 标号统一替换为 ①②③
    counter = 0
    new_chars: list[str] = []
    for ch in answer:
        if _CITATION_REGEX.fullmatch(ch):
            counter += 1
            new_chars.append(_CITATION_LABELS[counter - 1] if counter <= target_count else "")
        else:
            new_chars.append(ch)
    answer = "".join(new_chars)

    # 2. 数量对齐
    existing_count = len(_CITATION_REGEX.findall(answer))
    if existing_count < target_count:
        # 不足 → 文末补齐
        missing = _CITATION_LABELS[existing_count:target_count]
        return answer.rstrip() + "".join(missing)
    if existing_count > target_count:
        # 过多 → 从右到左删多余（保留前 target_count 个）
        keep_idx = 0
        result = []
        for ch in answer:
            if _CITATION_REGEX.fullmatch(ch):
                keep_idx += 1
                if keep_idx > target_count:
                    continue
            result.append(ch)
        return "".join(result)
    return answer
_META_QUERY_PATTERN = re.compile(
    r"("
    r"知识库[中有]?什么|知识库[中有]?哪[些|么]|"
    r"哪些[文档|内容|资料]|"
    r"有多少[文档|篇|个]|"
    r"统计|概览|清单|列表|总览|"
    r"所有文档|全部文档|"
    r"what('s| is) (in|available)|"
    r"list.*documents|how many"
    r")",
    re.IGNORECASE,
)


def _is_meta_query(q: str) -> bool:
    """判断是否属于元数据级查询（不需要走 RAG 文本检索）"""
    return bool(_META_QUERY_PATTERN.search(q or ""))


def _build_kb_metadata() -> dict:
    """构造知识库全量元数据（文档清单 + 分类清单 + 统计）"""
    docs = list(_documents.values())
    by_category: dict[str, list] = {}
    for d in docs:
        by_category.setdefault(d.category, []).append({
            "id": d.id,
            "title": d.title,
            "filename": d.filename,
            "file_type": d.file_type,
            "owner": d.owner,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "chunk_count": VectorStore.count_by_doc_id(d.id),
        })
    categories = sorted(by_category.keys())
    total_chunks = sum(c["chunk_count"] for items in by_category.values() for c in items)
    return {
        "total_documents": len(docs),
        "total_chunks": total_chunks,
        "total_categories": len(categories),
        "categories": [
            {"name": cat, "doc_count": len(items), "chunk_count": sum(c["chunk_count"] for c in items)}
            for cat, items in sorted(by_category.items())
        ],
        "documents": [
            {
                "id": d.id, "title": d.title, "category": d.category,
                "filename": d.filename, "file_type": d.file_type,
                "owner": d.owner,
                "chunk_count": VectorStore.count_by_doc_id(d.id),
            }
            for d in sorted(docs, key=lambda x: (x.category, x.title))
        ],
    }


@router.get("/meta-summary")
async def get_meta_summary():
    """任务 1.2：知识库元数据清单（用于元数据级查询与前端展示）"""
    return _build_kb_metadata()


@router.post("/ask")
async def ask_question(
    q: str = Query(..., description="问题"),
    model: Optional[str] = Query(None, description="指定模型名称"),
    session_id: Optional[str] = Query(None, description="会话ID，用于关联对话历史"),
    knowledge_base_id: str = Query("all", description="任务 2：知识库过滤，'all'表示不限"),
):
    """AI 问答 - RAG 非流式"""
    sid = session_id or "default"
    logger.info(f"[API] /ask | session={sid} | question={q[:50]}... | kb={knowledge_base_id}")

    # ─── 任务 4：健康检查 + 告警（系统级异常前先报状态） ───
    try:
        from app.core.embedding import get_embedding_service
        svc = get_embedding_service()
        # 兼容多种 embedding 实现的就绪判断
        is_ready = True
        for attr in ("is_loaded", "is_ready"):
            fn = getattr(svc, attr, None)
            if callable(fn):
                try:
                    is_ready = bool(fn())
                    break
                except Exception:
                    is_ready = True
        if not is_ready:
            logger.warning(f"[ALERT] Embedding 服务未就绪，/ask 性能可能下降或返回空结果")
    except Exception as _e:
        logger.error(f"[ALERT] Embedding 服务探活失败: {_e}", exc_info=True)
        # 注意：探活失败 ≠ Embedding 一定坏了；不直接拒绝请求，而是仅打告警
        # 真正的失败会由 RAGChainService 内部捕获并降级为 hash embedding

    try:
        # 1. 获取历史
        history = ChatMemoryChainManager.get_history(sid)

        # 2. 追问检测与查询扩展
        search_query = FollowUpDetector.expand_query(q, history)
        # 任务 L：同义词扩展（解决 BGE 短词召回低的问题）
        search_query = FollowUpDetector.expand_with_synonyms(search_query)
        logger.debug(
            f"[API] 检索查询 | original={q[:50]}... | "
            f"expanded={search_query[:80]}..."
        )

        # 3. RAG 问答（中心化入口）
        from app.core.query_cache import get_query_cache
        q_cache = get_query_cache()
        
        # 提取最近一轮历史作为缓存 key 因子
        history_str = "".join([f"{h['role']}:{h['content']}" for h in history[-2:]]) if history else ""
        cache_key = q_cache.make_key(search_query, knowledge_base_id, {"model": model, "history": history_str})
        
        cached_result = q_cache.get(cache_key)
        if cached_result:
            logger.info(f"[API] /ask 缓存命中 | session={sid} | key={cache_key}")
            result = cached_result
        else:
            result = RAGChainService.ask(search_query, history=history, model=model, knowledge_base_id=knowledge_base_id)
            q_cache.set(cache_key, result)

        # 4. 记录对话到记忆
        ChatMemoryChainManager.add_exchange(sid, q, result["answer"])

        logger.info(
            f"[API] /ask 完成 | session={sid} | "
            f"citations={len(result['citations'])} | "
            f"conf={result['confidence']:.3f}"
        )

        # 任务 1.3：引用标注与 citations 数量严格对齐
        aligned_answer = _align_citations(result["answer"], result["citations"])
        if aligned_answer != result["answer"]:
            logger.info(
                f"[API] /ask 引用已对齐 | was_len={len(result['answer'])} | "
                f"now_len={len(aligned_answer)} | citations={len(result['citations'])}"
            )

        # 任务 X：引用严格性校验——保证 100% 来自用户上传文档
        # system_faq 类的内置文档（__kb_*）不应混入用户文档场景
        is_sys_faq_intent = result.get("intent") == "system_faq"
        citations_filtered = result["citations"]
        if not is_sys_faq_intent:
            # 正常知识库问答：剔除内置 system_faq 文档（不应被混入）
            citations_filtered = [
                c for c in result["citations"]
                if not (c.get("doc_id") or "").startswith("__kb_")
            ]
            if len(citations_filtered) != len(result["citations"]):
                logger.info(
                    f"[API] /ask 剔除内置 system_faq 引用 "
                    f"{len(result['citations'])} → {len(citations_filtered)}"
                )

        return {
            "success": True,
            "question": q,
            "answer": aligned_answer,
            "model": model,
            "citations": citations_filtered,
            "confidence": result["confidence"],
            # 任务 6：透传意图识别结果（用于可观测性 & 前端调试）
            "intent": result.get("intent"),
            "intent_confidence": result.get("intent_confidence"),
            "is_chitchat": result.get("is_chitchat", False),
            "is_meta_query": result.get("is_meta_query", False),
            "is_negation": result.get("is_negation", False),
        }
    except Exception as e:
        logger.error(f"[API] /ask 异常: {e}", exc_info=True)
        # 任务 4：分类告警
        err_type = type(e).__name__
        if "subscriptable" in str(e):
            logger.critical(f"[ALERT] Pydantic/Document 类型访问异常，建议检查 Document 类的 __getitem__ 兼容性: {e}")
        elif "Connection" in err_type or "Timeout" in err_type:
            logger.critical(f"[ALERT] LLM/Embedding 外部连接失败，可能影响服务可用性: {e}")
        return {
            "success": False,
            "error": str(e),
            "error_type": err_type,
            "answer": f"抱歉，处理失败: {str(e)}",
        }


@router.post("/ask/stream")
async def ask_question_stream(
    q: str = Query(..., description="问题"),
    model: Optional[str] = Query(None, description="指定模型名称"),
    context: Optional[list] = None,
    session_id: Optional[str] = Query(None, description="会话ID，用于关联对话历史"),
    selected_categories: Optional[list] = Query(None, description="v2：按分类过滤检索（空/缺省=全库）"),
    knowledge_base_id: str = Query("all", description="任务 2：知识库过滤，'all'表示不限"),
):
    """AI 问答 - RAG 流式（SSE）"""
    sid = session_id or "default"
    logger.info(f"[API] /ask/stream | session={sid} | question={q[:50]}... | kb={knowledge_base_id}")

    async def generate():
        try:
            # 1. 同步前端历史到记忆
            if context and isinstance(context, list):
                ChatMemoryChainManager.sync_from_context(sid, context)

            # 2. 获取历史
            history = ChatMemoryChainManager.get_history(sid)

            # 3. 追问检测与查询扩展
            search_query = FollowUpDetector.expand_query(q, history)
            # 任务 L：同义词扩展
            search_query = FollowUpDetector.expand_with_synonyms(search_query)
            logger.debug(f"[API] 流式检索查询 | expanded={search_query[:80]}...")

            # 4. 检查缓存
            from app.core.query_cache import get_query_cache
            q_cache = get_query_cache()
            history_str = "".join([f"{h['role']}:{h['content']}" for h in history[-2:]]) if history else ""
            cache_key = q_cache.make_key(search_query, knowledge_base_id, {"model": model, "history": history_str, "categories": str(selected_categories)})
            
            cached_result = q_cache.get(cache_key)
            if cached_result:
                logger.info(f"[API] /ask/stream 缓存命中 | session={sid} | key={cache_key}")
                # 模拟流式输出
                metadata_event = {
                    "type": "metadata",
                    "citations": cached_result.get("citations", []),
                    "confidence": cached_result.get("confidence", 1.0),
                    "model": model or "cached"
                }
                yield f"data: {json.dumps(metadata_event, ensure_ascii=False)}\n\n"
                
                text_event = {
                    "type": "text",
                    "content": cached_result.get("answer", "")
                }
                yield f"data: {json.dumps(text_event, ensure_ascii=False)}\n\n"
                
                done_event = {"type": "done"}
                yield f"data: {json.dumps(done_event, ensure_ascii=False)}\n\n"
                
                if cached_result.get("answer"):
                    ChatMemoryChainManager.add_exchange(sid, q, cached_result["answer"])
                return

            # 5. RAG 流式生成（中心化入口）
            collected_text = ""
            final_metadata = {}
            for event in RAGChainService.stream_ask(
                search_query,
                history=history,
                model=model,
                categories=selected_categories or None,
                knowledge_base_id=knowledge_base_id,
            ):
                event_type = event.get("type")

                if event_type == "metadata":
                    final_metadata = event
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

                elif event_type == "text":
                    collected_text += event["content"]
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

                elif event_type == "done":
                    # 流式完成后记录到记忆并缓存
                    if collected_text:
                        ChatMemoryChainManager.add_exchange(sid, q, collected_text)
                        q_cache.set(cache_key, {
                            "answer": collected_text,
                            "citations": final_metadata.get("citations", []),
                            "confidence": final_metadata.get("confidence", 1.0),
                            "intent": final_metadata.get("intent")
                        })
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    logger.info(
                        f"[API] /ask/stream 完成 | session={sid} | "
                        f"len={len(collected_text)}"
                    )

                elif event_type == "error":
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    logger.error(f"[API] /ask/stream 错误: {event.get('content')}")

        except Exception as e:
            logger.error(f"[API] /ask/stream 异常: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@router.post("/ask/clear")
async def clear_session_memory(
    session_id: Optional[str] = Query(None, description="要清除记忆的会话ID")
):
    """清除指定会话的对话记忆"""
    sid = session_id or "default"
    ChatMemoryChainManager.delete_memory(sid)
    logger.info(f"[API] /ask/clear | session={sid}")
    return {"success": True, "message": f"会话 {sid} 的记忆已清除"}


# ==================== 后台任务模式 ====================

@router.post("/ask/async")
async def ask_question_async(
    q: str = Query(..., description="问题"),
    model: Optional[str] = Query(None, description="指定模型名称"),
    session_id: Optional[str] = Query(None, description="会话ID"),
    context: Optional[list] = None,
    selected_categories: Optional[list] = Query(None, description="v2：按分类过滤检索"),
):
    """提交问答任务，立即返回 task_id。后台执行流式生成，前端可轮询 /tasks/{task_id} 获取结果。

    解决问题：用户切走页面后组件 unmount 不会杀掉后端任务，答案仍持续生成。

    v2：支持 selected_categories 参数，按分类过滤检索。
    """
    sid = session_id or "default"
    mgr = get_task_manager()
    task = mgr.create(
        question=q,
        session_id=sid,
        model=model,
        selected_categories=selected_categories or [],
    )
    mgr.update(task.task_id, status="running")

    def _run():
        """后台线程：执行完整的 RAG 流式生成，每收到一个 token 累积到 task.text"""
        try:
            if context and isinstance(context, list):
                ChatMemoryChainManager.sync_from_context(sid, context)
            history = ChatMemoryChainManager.get_history(sid)
            search_query = FollowUpDetector.expand_query(q, history)
            # 任务 L：同义词扩展
            search_query = FollowUpDetector.expand_with_synonyms(search_query)

            # 检查缓存
            from app.core.query_cache import get_query_cache
            q_cache = get_query_cache()
            history_str = "".join([f"{h['role']}:{h['content']}" for h in history[-2:]]) if history else ""
            cache_key = q_cache.make_key(search_query, "all", {"model": model, "history": history_str, "categories": str(selected_categories)})
            
            cached_result = q_cache.get(cache_key)
            if cached_result:
                logger.info(f"[API] /ask/async 缓存命中 | task_id={task.task_id} | key={cache_key}")
                mgr.update(
                    task.task_id,
                    status="done",
                    citations=cached_result.get("citations", []),
                    confidence=cached_result.get("confidence", 1.0),
                    model=model or "cached"
                )
                mgr.append_text(task.task_id, cached_result.get("answer", ""))
                if cached_result.get("answer"):
                    ChatMemoryChainManager.add_exchange(sid, q, cached_result["answer"])
                return

            # 任务 K（ai.py 层）：未找到 markers 检测 + 截断
            # 注意：不要把"知识库中找到"放进 not_found_markers
            # 原因：会触发 _truncate_at_not_found 截断到 marker 之前最近句号
            # → 留下"知识库中找到关于『X』的相关资料。"这种矛盾片段（"找到"但没内容）
            # 矛盾文案走专门的 contradiction 检测（done 事件里），不通过截断处理
            not_found_markers = [
                "未找到", "未提供", "没有找到", "暂未找到", "未找到相关", "没有相关", "知识库中暂未",
            ]
            # 矛盾 markers：LLM 自相矛盾的输出（任务 Z v3 重新设计）
            contradiction_markers = [
                "换个问法", "换种问法", "换个问题", "建议重新提问",
                "知识库中找到",  # LLM 违反 prompt 规定的矛盾表述
            ]

            def _truncate_at_not_found(text: str) -> str:
                """任务 O：找所有 marker 中 idx 最早的（位置最靠前），截到该位置后最近句末标点

                修复 bug：之前按 list 顺序找 marker，break 后截到 list 中靠后但答案中靠后的 marker
                → 答案前面的"知识库中提到了 X、Y、Z"概念介绍仍保留
                修复后：取所有 marker 中 idx 最早的（答案中靠前），确保前面的"知识库中提到..."段也被截断
                """
                earliest_idx = -1
                for marker in not_found_markers:
                    idx = text.find(marker)
                    if idx >= 0 and (earliest_idx < 0 or idx < earliest_idx):
                        earliest_idx = idx
                if earliest_idx < 0:
                    return text
                # 取 earliest_idx 后所有标点中最近的一个
                candidates = []
                for term in ['。', '!', '！', '?', '？', '\n', '；']:
                    end_idx = text.find(term, earliest_idx)
                    if end_idx > earliest_idx:
                        candidates.append(end_idx)
                if candidates:
                    return text[:min(candidates) + 1]
                return text[:earliest_idx + 4]

            for event in RAGChainService.stream_ask(
                search_query,
                history=history,
                model=model,
                categories=selected_categories or None,
            ):
                et = event.get("type")
                if et == "metadata":
                    mgr.update(
                        task.task_id,
                        citations=event.get("citations", []),
                        confidence=event.get("confidence", 0.0),
                        model=event.get("model"),
                        # 任务 Z v3：保存 context_docs 供兜底改写时调用 LLM 重新生成
                        context_docs=event.get("context_docs", []),
                    )
                elif et == "text":
                    mgr.append_text(task.task_id, event.get("content", ""))
                    # 任务 Z v3：取消流式过程中的暴力截断（_truncate_at_not_found）
                    # 原因：流式截断会掐断 LLM 还没说完的内容，导致用户看到"半句话"
                    # 改为 done 事件统一处理：完整保留 LLM 输出，矛盾 marker 走兜底改写
                    # （_truncate_at_not_found 函数保留，供非流式版本使用）
                elif et == "done":
                    # 任务 1.3：引用标注与 citations 数量严格对齐
                    t = mgr.get(task.task_id)
                    citations_list = t.citations if t else []
                    final_text = t.text if t else ""

                    # 任务 P3-7 修复：取消任务 Z 兜底改写（不要把 LLM 的正确答案覆盖为"抱歉"）
                    # 原因：之前的"未找到" marker 检测会把 LLM 输出中有"未找到"字眼的整段答案覆盖
                    # → 用户看到 1045 字符的正确答案（含 Markdown 表格）被改成 63 字符的"抱歉..."
                    # 新策略：完全信任 LLM 输出（_sanitize_llm_output 已清洗 [object Object] 等占位符）
                    # 仅在 LLM 输出为空时才走兜底模板
                    if not final_text or len(final_text.strip()) < 5:
                        # LLM 输出为空 → 用兜底模板
                        logger.info(
                            f"[API] /ask/async 兜底改写（v5 - 任务 P3-7）| "
                            f"task_id={task.task_id} | len={len(final_text)} | 空输出兜底"
                        )
                        from app.core.knowledge_provider import get_knowledge_provider
                        new_answer = get_knowledge_provider().get_template(
                            "empty_answer",
                            question=q,
                        )
                        mgr.replace_text(task.task_id, new_answer)
                        final_text = new_answer
                    else:
                        logger.info(
                            f"[API] /ask/async 保留 LLM 原输出 | "
                            f"task_id={task.task_id} | len={len(final_text)}"
                        )

                    if t and citations_list is not None and citations_list:
                        aligned = _align_citations(final_text, citations_list)
                        if aligned != final_text:
                            logger.info(
                                f"[API] /ask/async 引用已对齐 | task_id={task.task_id} | "
                                f"was_len={len(final_text)} | now_len={len(aligned)} | "
                                f"citations={len(citations_list)}"
                            )
                            mgr.replace_text(task.task_id, aligned)
                            final_text = aligned
                    if final_text:
                        ChatMemoryChainManager.add_exchange(sid, q, final_text)
                        # 写入缓存
                        q_cache.set(cache_key, {
                            "answer": final_text,
                            "citations": citations_list,
                            "confidence": t.confidence if t else 1.0
                        })
                    mgr.update(task.task_id, status="done")
                    logger.info(
                        f"[API] /ask/async 完成 | task_id={task.task_id} | "
                        f"len={len(final_text)}"
                    )
                elif et == "error":
                    mgr.update(
                        task.task_id,
                        status="error",
                        error=event.get("content", "unknown"),
                    )
        except Exception as e:
            logger.error(f"[API] /ask/async 任务异常: {e}", exc_info=True)
            mgr.update(task.task_id, status="error", error=str(e))

    threading.Thread(target=_run, daemon=True).start()

    return {
        "success": True,
        "task_id": task.task_id,
        "status": "running",
        "session_id": sid,
    }


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    """轮询任务状态。返回：status, text（已累积的答案）, citations, confidence 等。

    v2：额外返回 thinking（思考过程）和 answer（最终答案，已剥离 <think> 标签）。
    """
    task = get_task_manager().get(task_id)
    if not task:
        return {"success": False, "error": f"任务 {task_id} 不存在或已过期"}
    return {
        "success": True,
        "task_id": task.task_id,
        "session_id": task.session_id,
        "question": task.question,
        "status": task.status,
        "text": task.text,
        "thinking": task.thinking,
        "answer": task.answer,
        "citations": task.citations,
        "confidence": task.confidence,
        "model": task.model,
        "error": task.error,
        "selected_categories": task.selected_categories,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


@router.get("/tasks")
async def list_tasks(session_id: Optional[str] = None):
    """列出某 session 的所有任务（用于切回页面时恢复历史）"""
    sid = session_id or "default"
    tasks = get_task_manager().list_by_session(sid)
    return {
        "success": True,
        "session_id": sid,
        "tasks": [
            {
                "task_id": t.task_id,
                "question": t.question,
                "status": t.status,
                "text": t.text,
                "confidence": t.confidence,
                "citations": t.citations,
                "created_at": t.created_at,
                "updated_at": t.updated_at,
            }
            for t in sorted(tasks, key=lambda x: x.created_at, reverse=True)
        ],
    }


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    """删除指定任务"""
    get_task_manager().delete(task_id)
    return {"success": True}

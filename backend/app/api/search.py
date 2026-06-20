"""
搜索 API - 全部走 RAGChainService.retrieve()（中心化）

所有搜索端点都通过 RAG 的混合检索器（HybridRetriever）执行，
不允许直接调用 VectorStore / kg_service 绕过 RAG。
"""
import asyncio
import json
import logging
import time
from typing import List

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.core.rag_chain import RAGChainService, HybridRetriever
from app.services.knowledge_graph import KnowledgeGraphService

router = APIRouter()
logger = logging.getLogger(__name__)


def _docs_to_search_results(docs, snippet_len: int = 300) -> List[dict]:
    """把 LangChain Document 列表转换为统一搜索结果结构"""
    results = []
    for doc in docs:
        meta = doc.metadata.copy()
        score = meta.get("score", 0.0)
        results.append({
            "content": doc.page_content[:snippet_len],
            "metadata": meta,
            "score": float(score),
        })
    return results


def _docs_to_search_results_kw(docs, snippet_len: int = 500) -> List[dict]:
    """把关键词回退的 Document 列表转换为前端 text tab 期望的结构"""
    results = []
    for doc in docs:
        meta = doc.metadata.copy()
        score = meta.get("score", 0.0)
        doc_id = meta.get("doc_id", "")
        results.append({
            "snippet": doc.page_content[:snippet_len],
            "document": {
                "id": doc_id,
                "title": meta.get("title", "未知文档"),
                "content": doc.page_content,
                "category": meta.get("category", "默认"),
            },
            "score": float(score),
        })
    return results


@router.get("/")
@router.get("/hybrid")
async def hybrid_search(
    q: str = Query(..., description="搜索关键词"),
    limit: int = Query(10, ge=1, le=50),
    knowledge_base_id: str = Query("all", description="任务 2：知识库过滤，'all'表示不限"),
):
    """
    RAG 混合检索：向量语义 + 图谱 + 关键词
    同时执行三种检索，按类别返回，供前端 Tab 切换展示
    """
    logger.info(f"[Search] hybrid | q={q[:50]}... | limit={limit} | kb={knowledge_base_id}")
    try:
        # 1. 向量检索
        vector_docs = []
        try:
            v_retriever = HybridRetriever(
                top_k=limit,
                enable_kg=False,
                enable_keyword_fallback=False,
                knowledge_base_id=knowledge_base_id,
            )
            vector_docs = v_retriever.invoke(q)
        except Exception as e:
            logger.warning(f"[Search] 向量检索失败: {e}")

        # 2. 图谱检索
        graph_nodes = []
        graph_edges = []
        try:
            if knowledge_base_id == "all":
                # 合并所有 KB 的图谱检索
                from app.services.knowledge_base import _load_kbs
                kbs = _load_kbs()
                kb_ids = ["default"] + [k["id"] for k in kbs if k["id"] != "default"]
                all_nodes = []
                all_edges = []
                for kid in kb_ids:
                    kg = KnowledgeGraphService(knowledge_base_id=kid)
                    gr = kg.search_subgraph(q, depth=2)
                    all_nodes.extend(gr.get("nodes", []))
                    all_edges.extend(gr.get("edges", []))
                graph_nodes, graph_edges = all_nodes, all_edges
            else:
                kg_service = KnowledgeGraphService(knowledge_base_id=knowledge_base_id)
                graph_results = kg_service.search_subgraph(q, depth=2)
                graph_nodes = graph_results.get("nodes", [])
                graph_edges = graph_results.get("edges", [])
        except Exception as e:
            logger.warning(f"[Search] 图谱检索失败: {e}")

        # 3. 关键词检索（任务 B：直接调 _fallback_keyword_search，不被 vector_hits 条件拦截）
        text_docs = []
        try:
            text_docs = HybridRetriever._fallback_keyword_search(q, limit=limit)
        except Exception as e:
            logger.warning(f"[Search] 关键词检索失败: {e}")

        return {
            "query": q,
            "vector": _docs_to_search_results(vector_docs),
            "graph": {
                "nodes": graph_nodes,
                "edges": graph_edges,
            },
            "text": _docs_to_search_results_kw(text_docs),
        }
    except Exception as e:
        logger.error(f"[Search] hybrid 异常: {e}", exc_info=True)
        return {
            "query": q,
            "vector": [],
            "graph": {"nodes": [], "edges": []},
            "text": [],
            "error": str(e),
        }


@router.get("/hybrid/stream")
async def hybrid_search_stream(
    q: str = Query(..., description="搜索关键词"),
    limit: int = Query(10, ge=1, le=50),
    knowledge_base_id: str = Query("all", description="知识库过滤，'all'表示不限"),
):
    """任务 1.1+1.2：流式混合检索 + 进度推送（SSE）

    阶段：
    0% init
    20% vector
    50% graph
    75% keyword
    95% finalize
    100% done
    """
    async def event_generator():
        t0 = time.time()
        try:
            # ===== 阶段 0：初始化（5%）=====
            yield _sse("progress", {
                "stage": "init", "label": "初始化检索任务",
                "percent": 5, "elapsed_ms": 0, "remaining_ms": None
            })
            await asyncio.sleep(0.05)  # 让前端先看到

            # ===== 阶段 1：向量检索（5% → 30%）=====
            yield _sse("progress", {
                "stage": "vector", "label": "向量语义检索",
                "percent": 10, "elapsed_ms": int((time.time() - t0) * 1000)
            })
            vector_docs = []
            try:
                v_retriever = HybridRetriever(
                    top_k=limit,
                    enable_kg=False,
                    enable_keyword_fallback=False,
                    knowledge_base_id=knowledge_base_id,
                )
                # 任务 1.1 关键修复：invoke 是同步 IO，必须在子线程跑以释放 event loop
                vector_docs = await asyncio.to_thread(v_retriever.invoke, q)
                yield _sse("progress", {
                    "stage": "vector", "label": f"向量检索完成（{len(vector_docs)} 条）",
                    "percent": 30, "elapsed_ms": int((time.time() - t0) * 1000)
                })
            except Exception as e:
                logger.warning(f"[Search/Stream] 向量检索失败: {e}")
                yield _sse("warn", {"stage": "vector", "message": str(e)})

            # ===== 阶段 2：图谱检索（30% → 65%）=====
            yield _sse("progress", {
                "stage": "graph", "label": "知识图谱检索",
                "percent": 40, "elapsed_ms": int((time.time() - t0) * 1000)
            })
            graph_nodes = []
            graph_edges = []
            try:
                def _do_graph():
                    if knowledge_base_id == "all":
                        from app.services.knowledge_base import _load_kbs
                        kbs = _load_kbs()
                        kb_ids = ["default"] + [k["id"] for k in kbs if k["id"] != "default"]
                        all_nodes, all_edges = [], []
                        for kid in kb_ids:
                            kg = KnowledgeGraphService(knowledge_base_id=kid)
                            gr = kg.search_subgraph(q, depth=2)
                            all_nodes.extend(gr.get("nodes", []))
                            all_edges.extend(gr.get("edges", []))
                        return all_nodes, all_edges
                    else:
                        kg_service = KnowledgeGraphService(knowledge_base_id=knowledge_base_id)
                        gr = kg_service.search_subgraph(q, depth=2)
                        return gr.get("nodes", []), gr.get("edges", [])
                # 任务 1.1 关键修复：图谱检索也走子线程
                graph_nodes, graph_edges = await asyncio.to_thread(_do_graph)
                yield _sse("progress", {
                    "stage": "graph", "label": f"图谱检索完成（{len(graph_nodes)} 节点）",
                    "percent": 65, "elapsed_ms": int((time.time() - t0) * 1000)
                })
            except Exception as e:
                logger.warning(f"[Search/Stream] 图谱检索失败: {e}")
                yield _sse("warn", {"stage": "graph", "message": str(e)})

            # ===== 阶段 3：关键词回退（65% → 90%）=====
            yield _sse("progress", {
                "stage": "keyword", "label": "关键词全文检索",
                "percent": 75, "elapsed_ms": int((time.time() - t0) * 1000)
            })
            text_docs = []
            try:
                # 任务 B 关键修复：直接调 _fallback_keyword_search，不被 vector_hits 条件拦截
                text_docs = await asyncio.to_thread(HybridRetriever._fallback_keyword_search, q, limit)
                yield _sse("progress", {
                    "stage": "keyword", "label": f"关键词检索完成（{len(text_docs)} 条）",
                    "percent": 90, "elapsed_ms": int((time.time() - t0) * 1000)
                })
            except Exception as e:
                logger.warning(f"[Search/Stream] 关键词检索失败: {e}")
                yield _sse("warn", {"stage": "keyword", "message": str(e)})

            # ===== 阶段 4：完成（90% → 100%）=====
            await asyncio.sleep(0.05)
            final_data = {
                "query": q,
                "vector": _docs_to_search_results(vector_docs),
                "graph": {
                    "nodes": graph_nodes,
                    "edges": graph_edges,
                },
                "text": _docs_to_search_results_kw(text_docs),
            }
            yield _sse("done", {
                "percent": 100,
                "elapsed_ms": int((time.time() - t0) * 1000),
                "data": final_data
            })

        except Exception as e:
            logger.error(f"[Search/Stream] 异常: {e}", exc_info=True)
            yield _sse("error", {"message": str(e)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲
            "Connection": "keep-alive"
        }
    )


def _sse(event: str, data: dict) -> str:
    """构造 SSE 事件字符串"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/vector")
async def vector_search(
    q: str = Query(..., description="搜索关键词"),
    top_k: int = Query(10, ge=1, le=50)
):
    """仅向量语义检索（走 RAG 检索器，关掉 KG 和关键词回退）"""
    logger.info(f"[Search] vector | q={q[:50]}... | top_k={top_k}")
    try:
        retriever = HybridRetriever(
            top_k=top_k,
            enable_kg=False,
            enable_keyword_fallback=False,
        )
        docs = retriever.invoke(q)
        return {
            "query": q,
            "results": _docs_to_search_results(docs),
            "total": len(docs),
            "source": "vector",
        }
    except Exception as e:
        logger.error(f"[Search] vector 异常: {e}", exc_info=True)
        return {"query": q, "results": [], "total": 0, "error": str(e)}


@router.get("/graph")
async def search_graph(
    q: str = Query(..., description="关键词"),
    depth: int = Query(2, ge=1, le=3)
):
    """仅图谱检索（走 RAG 检索器，KG 模式）"""
    logger.info(f"[Search] graph | q={q[:50]}... | depth={depth}")
    try:
        # 用一个仅走 KG 的检索器
        retriever = HybridRetriever(
            top_k=0,  # 关闭向量
            kg_depth=depth,
            enable_kg=True,
            enable_keyword_fallback=False,
        )
        docs = retriever.invoke(q)
        return {
            "query": q,
            "nodes": [
                {
                    "name": d.metadata.get("entity_name", ""),
                    "type": d.metadata.get("entity_type", ""),
                    "content": d.page_content,
                }
                for d in docs
            ],
            "total": len(docs),
            "source": "knowledge_graph",
        }
    except Exception as e:
        logger.error(f"[Search] graph 异常: {e}", exc_info=True)
        return {"query": q, "nodes": [], "total": 0, "error": str(e)}


@router.get("/keyword")
async def keyword_search(
    q: str = Query(..., description="搜索关键词"),
    limit: int = Query(10, ge=1, le=50)
):
    """仅关键词回退检索（走 RAG 检索器，强制走 fallback）"""
    logger.info(f"[Search] keyword | q={q[:50]}... | limit={limit}")
    try:
        retriever = HybridRetriever(
            top_k=0,  # 关闭向量，让其走 fallback
            enable_kg=False,
            enable_keyword_fallback=True,
        )
        docs = retriever.invoke(q)
        return {
            "query": q,
            "results": _docs_to_search_results(docs, snippet_len=500),
            "total": len(docs),
            "source": "keyword_fallback",
        }
    except Exception as e:
        logger.error(f"[Search] keyword 异常: {e}", exc_info=True)
        return {"query": q, "results": [], "total": 0, "error": str(e)}

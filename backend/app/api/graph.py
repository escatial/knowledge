"""
知识图谱 API
"""
from fastapi import APIRouter

from app.services.knowledge_graph import kg_service, KnowledgeGraphService
from app.services.document_service import _documents

router = APIRouter()


@router.get("/")
async def get_graph(knowledge_base_id: str = "default"):
    """获取完整知识图谱（任务 2：按 KB 过滤）"""
    if knowledge_base_id == "all":
        # 合并所有 KB 的图谱
        from app.services.knowledge_base import _load_kbs
        all_nodes = []
        all_edges = []
        seen_node_ids = set()
        kbs = _load_kbs()
        # 包含 default + 所有自定义 KB
        kb_ids = ["default"] + [k["id"] for k in kbs if k["id"] != "default"]
        for kid in kb_ids:
            kg = KnowledgeGraphService(knowledge_base_id=kid)
            for n in kg._graph.get("nodes", []):
                if n["id"] not in seen_node_ids:
                    all_nodes.append(n)
                    seen_node_ids.add(n["id"])
            all_edges.extend(kg._graph.get("edges", []))
        return {"nodes": all_nodes, "edges": all_edges}
    kg = KnowledgeGraphService(knowledge_base_id=knowledge_base_id)
    return kg.get_graph()


@router.get("/node/{node_id}")
async def get_node_detail(node_id: str):
    """获取节点详情"""
    return kg_service.get_node_detail(node_id)


@router.get("/search")
async def search_graph(q: str, depth: int = 2):
    """搜索子图谱"""
    return kg_service.search_subgraph(q, depth)


@router.post("/gc")
async def graph_garbage_collect():
    """任务 2.3：垃圾回收 — 清理所有 doc_id 不在 documents.json 中的幽灵文档节点

    返回：
        removed_nodes, removed_edges, remaining_nodes, remaining_edges, details
    """
    live_doc_ids = set(_documents.keys())
    return kg_service.gc_orphan_nodes(live_doc_ids)


@router.post("/clean-doc-edges")
async def graph_clean_doc_edges():
    """任务 1.2 修复：清理所有 doc→doc 边（破坏图谱语义的错误设计残留）"""
    return kg_service.clean_doc_doc_edges()


@router.post("/audit")
async def graph_audit_and_clean():
    """图谱全面审查 + 清理（一次性执行所有规则）

    流程：备份 → 补全业务分类 → 合并同义变体 → 清理碎片 → 清理孤立 → 清理 doc→doc 边
    """
    return kg_service.audit_and_clean()


@router.post("/rebuild-orphans")
async def graph_rebuild_orphans():
    """任务 1.2（修订）：重建孤立活文档的图谱关联

    对每个孤立活文档（outEdges=0）重新触发 build_from_document：
    - 二次尝试 LLM 抽取（可能上次网络问题已恢复）
    - 失败时走 _ensure_min_connections，从 content 抽取概念关键词
    - 多个文档若共享同一概念实体，自然形成以概念为中心的星型聚类

    ⚠️ 绝不在文档间直接连边（破坏图谱语义）
    """
    return kg_service.rebuild_orphan_graph(_documents)


@router.post("/classify-entities")
async def graph_classify_entities():
    """任务 4：LLM 批量筛选实体价值 + 自动生成领域词表

    - 扫描所有 entity 节点
    - 调用 LLM 批量分类 keep/remove
    - 自动生成领域核心词表并持久化
    - 清理低价值节点及关联边
    """
    return kg_service.classify_entities_with_llm()


@router.post("/relate-cross-docs")
async def graph_relate_cross_docs():
    """任务 3：LLM 驱动的跨文档实体关联

    - 找出被多个文档引用的共享实体
    - 用 LLM 分析跨文档实体对之间的语义关系
    - 为确认有语义关联的实体对创建图谱边
    """
    return kg_service.relate_cross_document_entities()


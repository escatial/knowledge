"""
知识图谱服务
构建和管理实体关系图谱
"""
import json
import os
import re
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set

from app.core.config import settings
from app.core.llm import LLMService

logger = logging.getLogger(__name__)

# 确保目录存在
Path(settings.GRAPH_DATA_DIR).mkdir(parents=True, exist_ok=True)

GRAPH_FILE = Path(settings.GRAPH_DATA_DIR) / "graph.json"


def _graph_file_for_kb(knowledge_base_id: str = "default") -> Path:
    """任务 2：每个知识库独立的图谱文件"""
    if knowledge_base_id == "default":
        return Path(settings.GRAPH_DATA_DIR) / "graph.json"
    return Path(settings.GRAPH_DATA_DIR) / f"graph_kb_{knowledge_base_id}.json"


class KnowledgeGraphService:
    """知识图谱服务
    
    任务 2：支持知识库物理隔离，每个知识库有独立的 graph.json 文件
    """

    def __init__(self, knowledge_base_id: str = "default"):
        self.knowledge_base_id = knowledge_base_id
        self._graph_file = _graph_file_for_kb(knowledge_base_id)
        self._graph = self._load_graph()

    def _load_graph(self) -> dict:
        """加载图谱数据"""
        if self._graph_file.exists():
            with open(self._graph_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"nodes": [], "edges": []}

    def _save_graph(self):
        """保存图谱数据"""
        self._graph_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._graph_file, 'w', encoding='utf-8') as f:
            json.dump(self._graph, f, ensure_ascii=False, indent=2)
    
    def build_from_document(self, doc_id: str, title: str, content: str) -> dict:
        """从文档构建知识图谱

        修复 1.1：增加 LLM 抽取失败的 fallback 路径
        修复 1.x：增加 LLM 幻觉防御
          - 实体名必须直接出现在文档原文中（title + content 前 1500 字符）
          - 节点加 source_doc_ids provenance 字段
          - 拒绝 LLM 凭空生成的看似真实但实际不存在的实体
        任务 1（实体溯源单点修复）：入口处校验 provenance 有效性
          - 严格校验 doc_id / title / content 非空且合法
          - 确保文档节点创建成功后再处理实体
          - 实体创建后验证 source_doc_ids 完整性
        """
        # ===== 任务 1：入口参数校验 =====
        if not doc_id or not isinstance(doc_id, str) or not doc_id.strip():
            raise ValueError(f"[Graph] build_from_document 拒绝无效 doc_id: {doc_id!r}")
        doc_id = doc_id.strip()
        if not title or not isinstance(title, str) or not title.strip():
            raise ValueError(f"[Graph] build_from_document 拒绝空 title (doc_id={doc_id})")
        title = title.strip()
        if not content or not isinstance(content, str):
            raise ValueError(f"[Graph] build_from_document 拒绝空 content (doc_id={doc_id})")

        # 使用 LLM 提取实体和关系（异常保护：网络/解析失败不应阻塞 build）
        try:
            extracted = LLMService.extract_entities(content)
        except Exception as e:
            logger.warning(f"[Graph] LLM extract 失败（已降级到 fallback）: {e}")
            extracted = {"entities": [], "relations": []}
        entities = extracted.get("entities", []) if isinstance(extracted, dict) else []
        relations = extracted.get("relations", []) if isinstance(extracted, dict) else []

        # ===== 任务 1：确保文档节点存在且有效 =====
        doc_node_id = f"doc_{doc_id}"
        existing_docs = [n for n in self._graph.get("nodes", [])
                         if n.get("category") == "document" and n.get("id") == doc_node_id]

        if existing_docs:
            # 文档节点已存在，更新描述
            existing_docs[0]["description"] = f"文档: {title}"
            existing_docs[0]["name"] = title
        else:
            doc_node = {
                "id": doc_node_id,
                "name": title,
                "type": "文档",
                "description": f"文档: {title}",
                "doc_id": doc_id,
                "category": "document"
            }
            self._add_node(doc_node)

        # 验证文档节点已成功添加
        doc_node_exists = any(n.get("id") == doc_node_id for n in self._graph.get("nodes", []))
        if not doc_node_exists:
            raise RuntimeError(f"[Graph] 文档节点创建失败: doc_{doc_id}")

        # === 防 LLM 幻觉：实体名必须出现在文档原文中 ===
        # 防止 LLM 凭"知识"虚构看似真实但实际不存在的实体（如一本不存在的"手册"）
        source_text = (title or "") + " " + (content or "")[:1500]
        validated_entities = []
        rejected = []
        for e in entities:
            if not isinstance(e, dict) or not e.get("name"):
                continue
            name = str(e.get("name", "")).strip()
            if len(name) < 2:
                continue
            if name not in source_text:
                rejected.append({"name": name, "reason": "not_in_source_text"})
                logger.warning(f"[Graph] 拒绝 LLM 幻觉实体「{name}」: 不在文档原文中")
                continue
            # 任务 D：教学示例人名黑名单（防止 "我叫张三" 这类示例中的人名被当成真实体）
            if name in _EXAMPLE_PERSON_NAMES:
                rejected.append({"name": name, "reason": "example_placeholder_name"})
                logger.warning(f"[Graph] 拒绝教学示例人名「{name}」（非真实实体）")
                continue
            validated_entities.append(e)

        # 添加实体节点和关系
        entity_id_map = {}
        new_entity_ids = []  # 任务 1：记录本次新建的实体 ID 用于 provenance 验证
        for entity in validated_entities:
            # 去重：相同名称的实体合并
            existing = self._find_node_by_name(entity["name"])
            if existing:
                new_id = existing["id"]
                entity_id_map[entity["id"]] = new_id
                if entity.get("description"):
                    existing["description"] = entity["description"]
                # 维护 provenance：记录所有引用此实体的文档
                src = existing.setdefault("source_doc_ids", [])
                if doc_id not in src:
                    src.append(doc_id)
            else:
                import uuid
                new_id = f"ent_{uuid.uuid4().hex[:8]}"
                entity_id_map[entity["id"]] = new_id
                node = {
                    "id": new_id,
                    "name": entity["name"],
                    "type": entity.get("type", "概念"),
                    "description": entity.get("description", ""),
                    "category": "entity",
                    "source_doc_ids": [doc_id],  # 关键：provenance 字段
                }
                self._add_node(node)
                new_entity_ids.append(new_id)

            # 添加文档到实体的关系
            self._add_edge({
                "source": doc_node_id,
                "target": new_id,
                "type": "包含",
                "description": f"文档包含实体: {entity['name']}"
            })

        # 添加实体间关系
        for relation in relations:
            if not isinstance(relation, dict):
                continue
            source_id = entity_id_map.get(relation.get("source"))
            target_id = entity_id_map.get(relation.get("target"))
            if source_id and target_id:
                self._add_edge({
                    "source": source_id,
                    "target": target_id,
                    "type": relation.get("type", "相关"),
                    "description": relation.get("description", "")
                })

        # 修复 1.1 fallback：若 LLM 未抽取到任何有效实体，保底创建基础实体 + 边
        if not validated_entities:
            self._ensure_min_connections(doc_node_id, title, content)

        # ===== 任务 1：验证 provenance 完整性 =====
        provenance_issues = []
        for eid in new_entity_ids:
            node = next((n for n in self._graph["nodes"] if n["id"] == eid), None)
            if not node:
                provenance_issues.append(f"节点 {eid} 创建后丢失")
                continue
            src_ids = node.get("source_doc_ids", [])
            if doc_id not in src_ids:
                provenance_issues.append(f"节点 {eid} ({node.get('name')}) 缺少 source_doc_ids[{doc_id}]")
            # 验证边也存在
            edge_exists = any(
                e.get("source") == doc_node_id and e.get("target") == eid and e.get("type") == "包含"
                for e in self._graph.get("edges", [])
            )
            if not edge_exists:
                provenance_issues.append(f"节点 {eid} ({node.get('name')}) 缺少 doc→entity 包含边")

        if provenance_issues:
            logger.error(f"[Graph] provenance 验证失败 ({len(provenance_issues)} 项): {provenance_issues}")
        else:
            logger.debug(f"[Graph] provenance 验证通过，{len(new_entity_ids)} 个实体均可追溯至 doc_{doc_id}")

        self._save_graph()
        return {
            "nodes_added": len(validated_entities),
            "edges_added": len(relations) + len(validated_entities),
            "entities_rejected": len(rejected),
            "rejected_details": rejected,
            "provenance_valid": len(provenance_issues) == 0,
            "provenance_issues": provenance_issues,
        }

    def _ensure_min_connections(self, doc_node_id: str, title: str, content: str):
        """保底连接：LLM 抽取失败时为 doc 节点建立至少 1 条边

        设计原则（重要！）：
        - 文档是「资源」，概念是「节点核心」
        - 文档与文档之间**绝对不要直接连边**（无语义价值，会形成无意义的随机网状图）
        - 多个文档**共享同一概念**时，自然形成以概念为中心的星型图谱

        策略：
        1. 创建「文档资源」基础实体（仅 1 个，所有文档共享）
        2. 从 title + content 前 800 字符抽取 5-8 个**概念关键词**（去停用词）
           - 多个文档若共享同一关键词，自动通过该概念实体聚类
        """
        # 1. 「文档资源」基础实体（全局共享）
        resource_entity = self._find_node_by_name("文档资源")
        if not resource_entity:
            import uuid
            resource_entity = {
                "id": f"ent_{uuid.uuid4().hex[:8]}",
                "name": "文档资源",
                "type": "概念",
                "description": "知识库中的文档资源根节点",
                "category": "entity",
            }
            self._add_node(resource_entity)
        self._add_edge({
            "source": doc_node_id,
            "target": resource_entity["id"],
            "type": "属于",
            "description": f"文档归属「文档资源」分类",
        })

        # 2. 概念关键词提取（title + content 前 800 字符）
        import re
        # 任务 D：教学/示例常用人名（防止 "我叫张三" 这类示例中被 LLM 误识别为真实实体）
        _EXAMPLE_PERSON_NAMES = {
            "张三", "李四", "王五", "赵六", "钱七", "孙八", "周九", "吴十",
            "小明", "小红", "小李", "小张", "小王", "小赵", "小刚", "小芳",
            "老王", "老李", "老张", "老赵", "老刘",
            "Alice", "Bob", "Charlie", "David", "Eve", "Frank", "Grace", "Henry",
            "John", "Jane", "Tom", "Jerry", "Mike", "Lily", "Lucy",
        }
        # 停用词：常见无意义 token（中文虚词 + 英文常见词 + 文档/章节前缀）
        STOPWORDS = {
            "一个", "一些", "这个", "那个", "什么", "怎么", "如何", "为什么",
            "PDF", "pdf", "docx", "DOCX", "txt", "TXT", "md", "MD",
            "文档", "文件", "教程", "实战", "基础", "进阶", "理论", "原理",
            "手册", "模板", "指南", "综述", "研究", "设计", "实现",
            "上篇", "下篇", "中篇", "第章", "章节", "附录", "前言",
            "the", "and", "for", "with", "this", "that", "from", "into",
        }
        text = (title or "") + " " + (content or "")[:800]
        # 抽取中文 ≥ 2 字 + 英文/数字 ≥ 3 字符
        tokens = re.findall(r'[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9]{2,}', text)
        # 去停用词、去重、保序
        seen = set()
        keywords = []
        for t in tokens:
            t_lower = t.lower()
            if t in STOPWORDS or t_lower in STOPWORDS:
                continue
            if t in seen or t_lower in seen:
                continue
            seen.add(t)
            seen.add(t_lower)
            keywords.append(t)
            if len(keywords) >= 8:
                break
        # 至少 1 个保底
        if not keywords and title:
            keywords = [title[:8]]

        for kw in keywords:
            kw_entity = self._find_node_by_name(kw)
            if not kw_entity:
                import uuid
                kw_entity = {
                    "id": f"ent_{uuid.uuid4().hex[:8]}",
                    "name": kw,
                    "type": "概念",
                    "description": f"从文档内容提取的主题概念：{kw}",
                    "category": "entity",
                }
                self._add_node(kw_entity)
            self._add_edge({
                "source": doc_node_id,
                "target": kw_entity["id"],
                "type": "提及",
                "description": f"文档提及概念「{kw}」",
            })

    def rebuild_orphan_graph(self, documents_dict) -> dict:
        """任务 1.2（修订）：重建孤立活文档的图谱关联

        设计原则（核心）：
        - **文档是资源，概念是节点核心**
        - **文档与文档之间绝对不要直接连边**（无语义价值，会形成无意义的随机网状图）
        - 正确的聚类方式：让多文档通过**共享同一概念实体**自然形成星型图谱

        实现：对每个孤立活文档（outEdges=0），重新调用 build_from_document。
        LLM 抽取失败时自动走 _ensure_min_connections，从 content 抽取概念关键词。
        多个文档若共享同一关键词（如 "Agent"、"RAG"），自动通过该概念实体聚类。

        Returns:
            {"fixed": int, "details": [{"doc_id": ..., "concepts": [...]}]}
        """
        if not documents_dict:
            return {"fixed": 0, "details": []}

        live_doc_ids = set(documents_dict.keys())

        # 找出孤立 doc 节点（仅 outEdges=0 的活文档）
        orphans = []
        for n in self._graph.get("nodes", []):
            if n.get("category") != "document":
                continue
            node_id = str(n.get("id", ""))
            node_doc_id = n.get("doc_id")
            inferred = node_doc_id or (node_id[len("doc_"):] if node_id.startswith("doc_") else None)
            if not inferred or inferred not in live_doc_ids:
                continue
            has_out = any(
                e.get("source") == node_id
                for e in self._graph.get("edges", [])
            )
            if not has_out:
                orphans.append((node_id, inferred))

        details = []
        for node_id, doc_id in orphans:
            doc = documents_dict.get(doc_id)
            if not doc:
                continue
            # 重新触发 build：会让 LLM 二次尝试（如果网络恢复）
            # 失败时走 _ensure_min_connections，从 content 抽取概念关键词
            content = getattr(doc, "content", "") or ""
            title = doc.title or ""
            try:
                self.build_from_document(doc_id, title, content)
                # 收集本次新增的"概念"实体名
                node = next((n for n in self._graph["nodes"] if n["id"] == node_id), None)
                concepts = []
                if node:
                    for e in self._graph["edges"]:
                        if e.get("source") == node_id and e.get("type") in ("提及", "属于", "包含"):
                            tgt = next((n for n in self._graph["nodes"] if n["id"] == e.get("target")), None)
                            if tgt and tgt.get("category") == "entity":
                                concepts.append(tgt["name"])
                details.append({"doc_id": doc_id, "concepts": concepts})
            except Exception as e:
                logger.warning(f"[Graph] rebuild 文档 {doc_id} 失败: {e}")
                details.append({"doc_id": doc_id, "concepts": [], "error": str(e)})

        return {"fixed": len(details), "details": details}

    # 保留旧方法名作为别名（向后兼容老调用方）
    def relink_orphan_doc_nodes(self, documents_dict) -> dict:
        """向后兼容：旧版 relink 已废弃，调用 rebuild_orphan_graph

        ⚠️ 旧实现错误地创建 doc→doc「同类」边，破坏图谱语义
        ⚠️ 文档应当关联到概念，由共享概念自然聚类
        """
        return self.rebuild_orphan_graph(documents_dict)
    
    def _add_node(self, node: dict):
        """添加节点（去重）"""
        if not any(n["id"] == node["id"] for n in self._graph["nodes"]):
            self._graph["nodes"].append(node)
    
    def _add_edge(self, edge: dict):
        """添加边（去重）"""
        edge_key = (edge["source"], edge["target"], edge["type"])
        if not any(
            (e["source"], e["target"], e["type"]) == edge_key 
            for e in self._graph["edges"]
        ):
            self._graph["edges"].append(edge)
    
    def _find_node_by_name(self, name: str) -> Optional[dict]:
        """根据名称查找节点"""
        for node in self._graph["nodes"]:
            if node["name"] == name:
                return node
        return None
    
    def get_graph(self) -> dict:
        """获取完整图谱"""
        return self._graph

    def delete_by_doc_id(self, doc_id: str) -> dict:
        """级联删除指定文档关联的所有节点和边（v2 需求 2）

        修复：兼容历史节点的多种命名约定（id 以 doc_ 开头、doc_id 字段缺失等）

        Returns:
            {"removed_nodes": int, "removed_edges": int, "remaining_nodes": int, "remaining_edges": int}
        """
        before_nodes = len(self._graph.get("nodes", []))
        before_edges = len(self._graph.get("edges", []))

        related_node_ids = set()
        for n in self._graph.get("nodes", []):
            node_id = str(n.get("id", ""))
            node_doc_id = n.get("doc_id")
            # 1. 直接 doc_id 字段匹配
            if node_doc_id == doc_id:
                related_node_ids.add(node_id)
                continue
            # 2. id 以 doc_{doc_id} 开头（标准命名）
            if node_id == f"doc_{doc_id}":
                related_node_ids.add(node_id)
                continue
            # 3. 兼容：历史节点 category=document 且 id 中含 doc_id（防止 id 字段缺失场景）
            if n.get("category") == "document" and doc_id and doc_id in node_id:
                related_node_ids.add(node_id)

        new_nodes = [n for n in self._graph.get("nodes", []) if n["id"] not in related_node_ids]
        new_edges = [
            e for e in self._graph.get("edges", [])
            if e.get("source") not in related_node_ids
            and e.get("target") not in related_node_ids
        ]

        # 任务 E：清理孤儿 entity（本次删除波及的 entity，若删除后无任何边引用 → 一起删）
        connected_ids = set()
        for e in new_edges:
            connected_ids.add(e.get("source"))
            connected_ids.add(e.get("target"))
        pre_orphan_count = len(new_nodes)
        new_nodes = [
            n for n in new_nodes
            if n.get("category") != "entity" or n.get("id") in connected_ids
        ]
        orphan_removed = pre_orphan_count - len(new_nodes)
        if orphan_removed:
            logger.info(f"[Graph] delete_by_doc_id 清理孤儿 entity: {orphan_removed} 个")

        removed_nodes = before_nodes - len(new_nodes)
        removed_edges = before_edges - len(new_edges)

        self._graph["nodes"] = new_nodes
        self._graph["edges"] = new_edges
        self._save_graph()

        return {
            "removed_nodes": removed_nodes,
            "removed_edges": removed_edges,
            "remaining_nodes": len(new_nodes),
            "remaining_edges": len(new_edges),
        }

    def clean_doc_doc_edges(self) -> dict:
        """任务 1.2 修复：清理所有 doc→doc 边（破坏图谱语义的错误设计残留）

        Returns:
            {"removed_edges": int, "details": [...]}
        """
        # 构建 doc 节点 id 集合
        doc_node_ids = {n["id"] for n in self._graph.get("nodes", []) if n.get("category") == "document"}
        removed = []
        new_edges = []
        for e in self._graph.get("edges", []):
            if e.get("source") in doc_node_ids and e.get("target") in doc_node_ids:
                removed.append(e)
            else:
                new_edges.append(e)
        if removed:
            self._graph["edges"] = new_edges
            self._save_graph()
        return {
            "removed_edges": len(removed),
            "details": [{"source": e["source"], "target": e["target"], "type": e.get("type")} for e in removed],
        }

    # ==================== 任务：图谱遗留内容全面审查 + 清理 ====================
    def remove_hallucinated_nodes(self) -> dict:
        """任务：清理 LLM 幻觉产生的无依据节点

        清理规则（满足任一即清理）：
        1. 节点 type ∈ {产品, 技术} + 0 入边 + 无 provenance
        2. 节点 type ∈ {概念, 事件} + 0 入边 + 无 provenance + description 长度 >= 10
        3. 任意 type + 0 入边 + 无 provenance + description 含 LLM 总结特征关键词

        保护：
        - 不清 category=document 的节点
        - 不清 type ∈ {人物, 组织, 地点}（这些常无入边但是合理）
        - 不清任何有入边或有 provenance 的节点
        """
        HALLUCINATION_TYPES = {"产品", "技术", "概念", "事件"}
        LLM_HALLUCINATION_HINTS = [
            "一份系统化的", "完整的工作流", "完整的提示词",
            "系统化的方法", "完整的科研", "关键场景",
            "实战手册", "工作流程指南",
        ]
        # 缓存现有 doc 节点 id 集合（用于 provenance 有效性检查）
        existing_doc_ids = {
            nn["id"] for nn in self._graph.get("nodes", [])
            if nn.get("category") == "document"
        }
        cleared = []
        for n in list(self._graph.get("nodes", [])):
            if n.get("category") == "document":
                continue
            ntype = n.get("type", "")
            if ntype not in HALLUCINATION_TYPES:
                continue
            desc = n.get("description", "")
            has_in = any(e.get("target") == n["id"] for e in self._graph.get("edges", []))
            if has_in:
                continue
            # 检查 provenance 是否真实有效（节点存在 + doc 节点存在）
            prov = n.get("source_doc_ids", [])
            has_valid_provenance = False
            if prov:
                for doc_id in prov:
                    if f"doc_{doc_id}" in existing_doc_ids:
                        has_valid_provenance = True
                        break
            if has_valid_provenance:
                continue
            # 满足清理条件之一：
            # (a) 产品/技术类型
            # (b) 概念/事件类型 + desc 长度 >= 10
            # (c) description 含 LLM 总结特征关键词
            # (d) 有 provenance 但指向已不存在的 doc（link bug 残留）
            should_clear = (
                ntype in {"产品", "技术"}
                or (ntype in {"概念", "事件"} and desc and len(desc) >= 10)
                or any(hint in desc for hint in LLM_HALLUCINATION_HINTS)
                or (bool(prov) and not has_valid_provenance)  # 有 provenance 但 link 失败
            )
            if not should_clear:
                continue
            cleared.append({
                "id": n["id"],
                "name": n.get("name"),
                "type": ntype,
                "description": desc[:80] if desc else "",
            })

        if not cleared:
            return {"removed_nodes": 0, "removed_edges": 0, "details": []}

        cleared_ids = {c["id"] for c in cleared}
        before_nodes = len(self._graph["nodes"])
        before_edges = len(self._graph["edges"])
        self._graph["nodes"] = [n for n in self._graph["nodes"] if n["id"] not in cleared_ids]
        self._graph["edges"] = [
            e for e in self._graph["edges"]
            if e.get("source") not in cleared_ids and e.get("target") not in cleared_ids
        ]
        self._save_graph()
        return {
            "removed_nodes": before_nodes - len(self._graph["nodes"]),
            "removed_edges": before_edges - len(self._graph["edges"]),
            "details": cleared,
        }

    def link_orphan_concepts_to_live_docs(self, documents_dict) -> dict:
        """任务：把孤立无 provenance 的真实 concept 节点关联到同分类活文档

        适用场景：ent_5 这类幽灵清理后，原本被它"承载"的端点概念变成孤立。
        这些端点是真实概念（不是幻觉），应该被同分类活文档"继承"。

        策略：
        - 找出孤立无 provenance 的 entity 节点（type=概念/技术 等）
        - 仅当目标 doc 节点存在于图谱时，才给它们添加同分类活文档的 provenance + 「包含」边
        - 若目标 doc 节点不存在（如该 doc 节点被 GC 清理），则跳过此节点（让 remove_hallucinated 清理）

        注意：仅给 type=概念/技术/事件/产品 的节点补充；type=人物/组织/地点 不动（它们常无入边但是合理）
        """
        RELINKABLE_TYPES = {"概念", "技术", "事件", "产品"}
        live_by_category: dict[str, list[str]] = {}
        for doc_id, doc in documents_dict.items():
            cat = getattr(doc, "category", "默认")
            live_by_category.setdefault(cat, []).append(doc_id)
        if not any(live_by_category.values()):
            return {"linked": 0, "details": []}

        # 缓存现有 doc 节点 id 集合
        existing_doc_ids = {nn["id"] for nn in self._graph["nodes"] if nn.get("category") == "document"}

        linked_count = 0
        details = []
        for n in self._graph.get("nodes", []):
            if n.get("category") == "document":
                continue
            ntype = n.get("type", "")
            if ntype not in RELINKABLE_TYPES:
                continue
            # 已有入边或已有 provenance → 跳过
            has_in = any(e.get("target") == n["id"] for e in self._graph.get("edges", []))
            has_provenance = bool(n.get("source_doc_ids"))
            if has_in or has_provenance:
                continue
            # 给它分配同分类活文档（如果有的话）
            name = n.get("name", "")
            target_cat = None
            if "Agent" in name or "规划" in name or "反应" in name or "智能" in name:
                target_cat = "agent" if "agent" in live_by_category else None
            if not target_cat:
                for cat in live_by_category:
                    if live_by_category[cat]:
                        target_cat = cat
                        break
            if not target_cat:
                continue
            # 关键修复：先在 live_by_category 中找到一个 doc 节点也存在于图谱的
            valid_doc_id = None
            for candidate_doc_id in live_by_category[target_cat]:
                candidate_node_id = f"doc_{candidate_doc_id}"
                if candidate_node_id in existing_doc_ids:
                    valid_doc_id = candidate_doc_id
                    break
            if not valid_doc_id:
                # 所有同分类活文档的 doc 节点都不在图谱中 → 跳过此节点（让 remove_hallucinated 清理）
                continue
            # 写入 provenance
            n["source_doc_ids"] = [valid_doc_id]
            # 加边
            doc_node_id = f"doc_{valid_doc_id}"
            self._add_edge({
                "source": doc_node_id,
                "target": n["id"],
                "type": "包含",
                "description": f"文档包含实体: {n.get('name')}",
            })
            linked_count += 1
            details.append({"node": n.get("name"), "linked_doc": valid_doc_id, "category": target_cat})

        if linked_count > 0:
            self._save_graph()
        return {"linked": linked_count, "details": details}

    def backup_graph(self) -> str:
        """备份当前图谱到带时间戳的备份文件

        Returns:
            备份文件绝对路径
        """
        import shutil
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self._graph_file.parent / f"graph_backup_{self.knowledge_base_id}_{ts}.json"
        shutil.copy2(self._graph_file, backup_path)
        logger.info(f"[Graph] 图谱已备份: {backup_path}")
        return str(backup_path)

    def merge_synonym_variants(self) -> dict:
        """合并同义变体节点：保留简写名作为主节点，删除带括号英文/冗余的变体

        合并规则：
        - "反应型Agent" + "反应型Agent（Reactive Agent）" → 保留前者
        - "规划型Agent" + "规划型Agent（Planning Agent）" → 保留前者
        - "感知模块" + "感知（Perception）" → 保留前者
        - "规划模块" + "规划（Planning）" → 保留前者
        - "反思模块" + "反思（Reflection）" → 保留前者
        - "LLM（大语言模型）" + "大模型" → 保留前者
        - "记忆模块" 单独保留（无变体）

        合并流程：
        1. 找到 (短名, 变体名) 对
        2. 把变体节点的入边重定向到主节点（去重）
        3. 把变体节点的出边重定向到主节点（去重）
        4. 删除变体节点

        Returns:
            {"merged": int, "edges_redirected": int, "details": [...]}
        """
        # 同义映射：变体名 -> 短名（主名）
        SYNONYM_PAIRS = [
            ("反应型Agent（Reactive Agent）", "反应型Agent"),
            ("规划型Agent（Planning Agent）", "规划型Agent"),
            ("感知（Perception）", "感知模块"),
            ("规划（Planning）", "规划模块"),
            ("反思（Reflection）", "反思模块"),
            ("大模型", "LLM（大语言模型）"),
        ]

        merged_count = 0
        edges_redirected = 0
        details = []

        for variant_name, primary_name in SYNONYM_PAIRS:
            variant = self._find_node_by_name(variant_name)
            primary = self._find_node_by_name(primary_name)
            if not variant:
                continue
            if not primary:
                # 变体在，主名不在 → 改名主名为变体的短名
                primary = variant
                primary["name"] = primary_name
                logger.info(f"[Graph] 合并同义：{variant_name} 重命名为主名 {primary_name}")
                merged_count += 1
                details.append({"variant": variant_name, "primary": primary_name, "action": "renamed"})
                continue

            if variant["id"] == primary["id"]:
                continue

            # 迁移变体的入边和出边到主节点
            for e in self._graph.get("edges", []):
                if e.get("source") == variant["id"]:
                    e["source"] = primary["id"]
                    edges_redirected += 1
                elif e.get("target") == variant["id"]:
                    e["target"] = primary["id"]
                    edges_redirected += 1

            # 删除变体节点
            self._graph["nodes"] = [n for n in self._graph["nodes"] if n["id"] != variant["id"]]
            merged_count += 1
            details.append({"variant": variant_name, "primary": primary_name, "action": "merged_and_redirected"})

        # 边去重（key = (source, target, type)）
        if edges_redirected > 0:
            seen = set()
            new_edges = []
            for e in self._graph.get("edges", []):
                key = (e.get("source"), e.get("target"), e.get("type"))
                if key not in seen:
                    seen.add(key)
                    new_edges.append(e)
            self._graph["edges"] = new_edges

        if merged_count > 0:
            self._save_graph()

        return {
            "merged": merged_count,
            "edges_redirected": edges_redirected,
            "details": details,
        }

    def remove_low_value_fragments(self) -> dict:
        """清理极低价值碎片节点

        规则：节点名在白名单中 → 整节点 + 关联边删除
        白名单：
        - "测试"（单字/极短）
        - "12个关键场景"（带数字的具体章节名，业务价值低）
        - "黄金提示词模板"（产品名/具体模板）
        - "论文图表生成"（具体功能，碎片化）
        - "多模型对比实验"（具体实验）
        - "润色优化与查重降重"（具体功能，碎片化）
        - "模块化设计"（抽象元概念，无具体业务价值）
        - "上海"（孤立地点节点，无连接）
        """
        FRAGMENT_NAMES = {
            "测试", "12个关键场景", "黄金提示词模板", "论文图表生成",
            "多模型对比实验", "润色优化与查重降重", "模块化设计", "上海",
            "fallback",  # LLM 异常时残留的英文占位词，无业务价值
        }
        # 找匹配节点
        target_ids = {n["id"] for n in self._graph["nodes"] if n.get("name") in FRAGMENT_NAMES}
        if not target_ids:
            return {"removed_nodes": 0, "removed_edges": 0, "details": []}

        before_nodes = len(self._graph["nodes"])
        before_edges = len(self._graph["edges"])

        self._graph["nodes"] = [n for n in self._graph["nodes"] if n["id"] not in target_ids]
        self._graph["edges"] = [
            e for e in self._graph["edges"]
            if e.get("source") not in target_ids and e.get("target") not in target_ids
        ]

        removed_nodes = before_nodes - len(self._graph["nodes"])
        removed_edges = before_edges - len(self._graph["edges"])
        self._save_graph()

        details = [
            {"id": nid, "name": n.get("name")}
            for n in [{"id": tid, "name": next((nn.get("name") for nn in self._graph["nodes"] + [{"id": tid, "name": "?"}] if nn.get("id") == tid), "?")} for tid in target_ids]
            for nn in [{"id": tid, "name": next((nn.get("name") for nn in [{"id": tid, "name": "?"}] if nn.get("id") == tid), "?")} for tid in target_ids]
        ] if False else []  # 简化
        # 实际用快照
        snap = {
            "测试": "测试", "12个关键场景": "12个关键场景", "黄金提示词模板": "黄金提示词模板",
            "论文图表生成": "论文图表生成", "多模型对比实验": "多模型对比实验",
            "润色优化与查重降重": "润色优化与查重降重", "模块化设计": "模块化设计", "上海": "上海",
        }
        details = [{"id": tid, "name": snap.get(nid, "?")} for tid in target_ids for nid in [tid]]

        return {
            "removed_nodes": removed_nodes,
            "removed_edges": removed_edges,
            "details": list(target_ids),
        }

    def _build_entity_classification_prompt(self, entities: List[dict]) -> str:
        """构建 LLM 批量实体价值分类 prompt

        任务 4：自动生成领域词表 + 分类 keep/remove
        """
        entity_lines = []
        for i, e in enumerate(entities):
            name = e.get("name", "")
            etype = e.get("type", "概念")
            desc = e.get("description", "")[:80]
            doc_count = len(e.get("source_doc_ids", []))
            entity_lines.append(f"{i+1}. 名称={name} | 类型={etype} | 描述={desc} | 引用文档数={doc_count}")

        prompt = f"""你是一个知识图谱质量审核专家。请对以下实体节点进行价值分类，判断哪些需要保留、哪些可以清理。

判定标准：
- **keep（保留）**：领域核心概念、技术术语、方法论、框架名称、具有明确语义价值的实体
- **remove（清理）**：过于碎片化的单一句子片段、无独立语义的辅助词、已过时或冗余的节点

请返回 JSON，格式如下：
{{
  "domain_vocabulary": ["核心术语1", "核心术语2", ...],  // 自动生成的知识领域核心词表
  "classifications": [
    {{"index": 1, "decision": "keep", "reason": "核心AI概念"}},
    {{"index": 2, "decision": "remove", "reason": "碎片化描述"}},
    ...
  ]
}}

待分类实体列表（共 {len(entities)} 个）：
{chr(10).join(entity_lines)}"""

        return prompt

    def classify_entities_with_llm(self) -> dict:
        """任务 4：LLM 批量筛选实体价值 + 生成领域词表

        Returns:
            {
                "total": int,           # 总实体数
                "to_keep": int,         # 保留数
                "to_remove": int,       # 建议清理数
                "domain_vocabulary": List[str],  # 自动生成的领域词表
                "classifications": List[dict],   # 每个实体的分类结果
                "removed_nodes": int,   # 实际已清理节点数
                "removed_edges": int,   # 实际已清理边数
            }
        """
        # 收集所有 entity 类别节点（排除 document 类别）
        entity_nodes = [
            n for n in self._graph.get("nodes", [])
            if n.get("category") == "entity" or n.get("category") not in ("document", None)
        ]
        if not entity_nodes:
            return {"total": 0, "to_keep": 0, "to_remove": 0,
                    "domain_vocabulary": [], "classifications": [],
                    "removed_nodes": 0, "removed_edges": 0}

        # 构建 prompt 并调用 LLM
        prompt = self._build_entity_classification_prompt(entity_nodes)
        try:
            result = LLMService.classify_entities(prompt)
        except Exception as e:
            logger.error(f"[Graph] LLM 实体分类失败: {e}")
            return {"total": len(entity_nodes), "to_keep": len(entity_nodes),
                    "to_remove": 0, "domain_vocabulary": [],
                    "classifications": [], "error": str(e),
                    "removed_nodes": 0, "removed_edges": 0}

        classifications = result.get("classifications", []) if isinstance(result, dict) else []
        domain_vocab = result.get("domain_vocabulary", []) if isinstance(result, dict) else []

        # 解析分类结果 → 找到要删除的节点 ID
        remove_indices = set()
        for c in classifications:
            if isinstance(c, dict) and c.get("decision") == "remove":
                remove_indices.add(c.get("index", -1) - 1)  # 转为 0-based

        keep_count = len(entity_nodes) - len(remove_indices)
        remove_ids = set()
        for idx in remove_indices:
            if 0 <= idx < len(entity_nodes):
                remove_ids.add(entity_nodes[idx]["id"])

        # 实际清理
        before_nodes = len(self._graph["nodes"])
        before_edges = len(self._graph["edges"])

        if remove_ids:
            self._graph["nodes"] = [n for n in self._graph["nodes"] if n["id"] not in remove_ids]
            self._graph["edges"] = [
                e for e in self._graph["edges"]
                if e.get("source") not in remove_ids and e.get("target") not in remove_ids
            ]
            self._save_graph()

        removed_nodes = before_nodes - len(self._graph["nodes"])
        removed_edges = before_edges - len(self._graph["edges"])

        # 持久化领域词表
        self._save_domain_vocabulary(domain_vocab)

        return {
            "total": len(entity_nodes),
            "to_keep": keep_count,
            "to_remove": len(remove_ids),
            "domain_vocabulary": domain_vocab,
            "classifications": classifications,
            "removed_nodes": removed_nodes,
            "removed_edges": removed_edges,
        }

    def _save_domain_vocabulary(self, vocab: List[str]):
        """持久化领域词表到文件"""
        vocab_path = self._graph_file.parent / "domain_vocabulary.json"
        existing = []
        if vocab_path.exists():
            try:
                existing = json.loads(vocab_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        # 合并去重
        merged = list(dict.fromkeys(existing + vocab))
        vocab_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"[Graph] 领域词表已更新: {len(merged)} 个术语")

    def relate_cross_document_entities(self) -> dict:
        """任务 3：LLM 驱动的跨文档实体关联

        在当前图谱中：
        - 同一文档内的实体已通过「文档→实体」边连接
        - 但不同文档间的实体没有直接边的建立逻辑

        本方法：
        1. 找出被多个文档引用的共享实体
        2. 对于同一共享实体关联的不同文档中的其他实体，用 LLM 判断是否存在语义关系
        3. 仅添加有实际语义关联的边（避免无意义的全连接）

        Returns:
            {
                "pairs_analyzed": int,
                "relations_added": int,
                "details": [{"source": str, "target": str, "type": str, "reason": str}]
            }
        """
        # 1. 找出共享实体（被 >=2 个文档引用）
        shared_entities = []
        for n in self._graph.get("nodes", []):
            if n.get("category") == "document":
                continue
            doc_ids = n.get("source_doc_ids", [])
            if len(doc_ids) >= 2:
                shared_entities.append(n)

        if len(shared_entities) < 2:
            return {"pairs_analyzed": 0, "relations_added": 0, "details": []}

        # 2. 构建候选实体对：同一共享实体关联的不同文档中的实体
        # 收集每个文档的实体集合
        doc_entities: dict[str, list[dict]] = {}
        for n in self._graph.get("nodes", []):
            if n.get("category") == "document":
                continue
            for doc_id in n.get("source_doc_ids", []):
                doc_entities.setdefault(doc_id, []).append(n)

        # 为每个共享实体找出跨文档候选对
        candidate_pairs = []
        seen_pairs = set()
        for shared in shared_entities:
            shared_docs = shared.get("source_doc_ids", [])
            for i, doc_a in enumerate(shared_docs):
                for doc_b in shared_docs[i + 1:]:
                    ents_a = [e for e in doc_entities.get(doc_a, []) if e["id"] != shared["id"]]
                    ents_b = [e for e in doc_entities.get(doc_b, []) if e["id"] != shared["id"]]
                    for ea in ents_a[:5]:  # 限制每个文档最多取5个
                        for eb in ents_b[:5]:
                            pair_key = tuple(sorted([ea["id"], eb["id"]]))
                            if pair_key in seen_pairs:
                                continue
                            seen_pairs.add(pair_key)
                            candidate_pairs.append((ea, eb))

        if not candidate_pairs:
            return {"pairs_analyzed": 0, "relations_added": 0, "details": []}

        # 限制最多分析 20 对
        candidate_pairs = candidate_pairs[:20]

        # 3. 构建 LLM prompt
        pair_lines = []
        for i, (ea, eb) in enumerate(candidate_pairs):
            pair_lines.append(
                f"{i+1}. [{ea.get('name', '?')}]（{ea.get('type', '?')}: {ea.get('description', '')[:50]}）"
                f" ↔ [{eb.get('name', '?')}]（{eb.get('type', '?')}: {eb.get('description', '')[:50]}）"
            )

        prompt = f"""你是一个知识图谱关联分析专家。请分析以下实体对之间是否存在有意义的语义关联。

判定标准：
- **related**：两个实体之间确实存在语义或逻辑关系（如：技术→应用场景、概念→子概念、工具→用途）
- **unrelated**：两个实体只是恰好在同一知识库中，没有实际关联

请返回 JSON，格式如下：
{{
  "relations": [
    {{"pair_index": 1, "decision": "related", "relation_type": "应用", "reason": "X是Y的应用场景"}},
    {{"pair_index": 2, "decision": "unrelated", "reason": "无实际语义关联"}}
  ]
}}

候选实体对：
{chr(10).join(pair_lines)}"""

        # 4. 调用 LLM
        try:
            result = LLMService.extract_cross_doc_relations(prompt)
        except Exception as e:
            logger.error(f"[Graph] 跨文档关联 LLM 调用失败: {e}")
            return {"pairs_analyzed": len(candidate_pairs), "relations_added": 0,
                    "details": [], "error": str(e)}

        rels = result.get("relations", []) if isinstance(result, dict) else []
        if not rels:
            return {"pairs_analyzed": len(candidate_pairs), "relations_added": 0, "details": []}

        # 5. 添加关系边
        added = []
        for rel in rels:
            if not isinstance(rel, dict) or rel.get("decision") != "related":
                continue
            idx = rel.get("pair_index", 0) - 1
            if idx < 0 or idx >= len(candidate_pairs):
                continue
            ea, eb = candidate_pairs[idx]
            edge_type = rel.get("relation_type", "相关")
            if edge_type not in {"属于", "创建", "使用", "位于", "参与", "相关", "包含", "应用", "依赖", "对比"}:
                edge_type = "相关"
            self._add_edge({
                "source": ea["id"],
                "target": eb["id"],
                "type": edge_type,
                "description": rel.get("reason", "LLM 识别的跨文档语义关联")
            })
            added.append({
                "source": ea.get("name"),
                "target": eb.get("name"),
                "type": edge_type,
                "reason": rel.get("reason", "")
            })

        if added:
            self._save_graph()

        return {
            "pairs_analyzed": len(candidate_pairs),
            "relations_added": len(added),
            "details": added,
        }

    def audit_and_clean(self) -> dict:
        """图谱全面审查 + 清理（一次性执行所有清理规则）

        清理规则：
        1. 备份原图谱
        2. 补全 categories.json 中缺失的业务分类
        3. 合并 6 对同义变体（保留简写）
        4. 清理 8 个极低价值碎片节点
        5. 清理 1 个孤立节点
        6. 清理历史 doc→doc 边
        7. 清理 LLM 幻觉产生的无依据产品/技术节点

        Returns:
            {
                "backup": str,
                "category_added": list,
                "merged": dict,
                "fragments_removed": dict,
                "hallucinated_removed": dict,
                "doc_doc_edges_removed": int,
                "before": {"nodes": int, "edges": int},
                "after": {"nodes": int, "edges": int},
            }
        """
        before = {
            "nodes": len(self._graph.get("nodes", [])),
            "edges": len(self._graph.get("edges", [])),
        }
        result = {
            "before": before,
            "before_action": "图谱全面审查 + 清理",
        }

        # 1. 备份
        try:
            result["backup"] = self.backup_graph()
        except Exception as e:
            logger.warning(f"[Graph] 备份失败: {e}")
            result["backup"] = f"备份失败: {e}"

        # 2. 补全业务分类（任务 P0-2: 优先 SQLite，fallback JSON）
        try:
            from pathlib import Path as _Path
            import json as _json
            cats = {}
            # 任务 P0-2: 优先 SQLite
            try:
                from app.core.db import get_db_session
                from app.core.models import Category
                with get_db_session() as session:
                    for r in session.query(Category).all():
                        cats[r.id] = {"strategy": r.strategy, "chunk_size": r.chunk_size, "overlap": r.overlap}
            except Exception:
                # Fallback JSON
                cats_file = _Path(__file__).resolve().parents[2] / "data" / "categories.json"
                with open(cats_file, "r", encoding="utf-8") as f:
                    cats = _json.load(f)
            added = []
            # 收集所有实际使用到的分类（从 SQLite 的 documents 读，fallback JSON）
            used_cats = set()
            try:
                from app.core.db import get_db_session
                from app.core.models import Document
                with get_db_session() as session:
                    for d in session.query(Document).all():
                        if d.category:
                            used_cats.add(d.category)
            except Exception:
                try:
                    docs_file = _Path(__file__).resolve().parents[2] / "data" / "documents.json"
                    with open(docs_file, "r", encoding="utf-8") as f:
                        docs = _json.load(f)
                    if isinstance(docs, dict):
                        docs = list(docs.values())
                    used_cats = {d.get("category") for d in docs if isinstance(d, dict) and d.get("category")}
                except Exception:
                    pass
            for cat in used_cats:
                if cat and cat not in cats:
                    # 复用「默认」配置
                    cats[cat] = dict(cats.get("默认", {"strategy": "recursive", "chunk_size": 500, "overlap": 100}))
                    added.append(cat)
            if added:
                # 任务 P0-2: 写回 SQLite
                try:
                    from app.core.db import get_db_session
                    from app.core.models import Category as _Cat
                    with get_db_session() as session:
                        for name, cfg in cats.items():
                            existing = session.query(_Cat).filter_by(id=name).first()
                            if existing:
                                existing.strategy = cfg["strategy"]
                                existing.chunk_size = cfg["chunk_size"]
                                existing.overlap = cfg["overlap"]
                            else:
                                session.add(_Cat(id=name, **cfg))
                except Exception:
                    # Fallback JSON
                    cats_file = _Path(__file__).resolve().parents[2] / "data" / "categories.json"
                    with open(cats_file, "w", encoding="utf-8") as f:
                        _json.dump(cats, f, ensure_ascii=False, indent=2)
            result["category_added"] = added
        except Exception as e:
            result["category_added"] = f"失败: {e}"

        # 3. 合并同义变体
        result["merged"] = self.merge_synonym_variants()

        # 4. 清理碎片
        result["fragments_removed"] = self.remove_low_value_fragments()

        # 5. 清理 LLM 幻觉节点（新增：优先于此步骤，确保孤立产品节点被识别）
        result["hallucinated_removed"] = self.remove_hallucinated_nodes()

        # 5.5 关联孤立真实概念节点到活文档（清理 ent_5 后被"遗留"的真实概念需重建 provenance）
        try:
            from app.services.document_service import _documents as _docs_dict
            result["orphan_concepts_linked"] = self.link_orphan_concepts_to_live_docs(_docs_dict)
        except Exception as e:
            result["orphan_concepts_linked"] = {"linked": 0, "details": [], "error": str(e)}

        # 6. 清理孤立
        try:
            live = set()  # 调用方传入；这里从 _documents 推
            from app.services.document_service import _documents
            live = set(_documents.keys())
            result["orphans_removed"] = self.gc_orphan_nodes(live)
        except Exception as e:
            result["orphans_removed"] = f"失败: {e}"

        # 7. 清理 doc→doc 边
        result["doc_doc_edges_removed"] = self.clean_doc_doc_edges()

        result["after"] = {
            "nodes": len(self._graph.get("nodes", [])),
            "edges": len(self._graph.get("edges", [])),
        }
        return result

    def gc_orphan_nodes(self, live_doc_ids: set) -> dict:
        """垃圾回收：清理所有 doc_id 不在 live_doc_ids 集合中的文档节点

        用于修复历史残留：图谱中存在但 documents.json 中已不存在的「幽灵节点」。
        同时清理指向幽灵节点的边。

        Args:
            live_doc_ids: 当前 documents.json 中所有活文档的 id 集合

        Returns:
            {"removed_nodes": int, "removed_edges": int, "remaining_nodes": int, "remaining_edges": int, "details": [...]}
        """
        before_nodes = len(self._graph.get("nodes", []))
        before_edges = len(self._graph.get("edges", []))

        ghost_ids = set()
        details = []
        for n in self._graph.get("nodes", []):
            if n.get("category") != "document":
                continue
            node_id = str(n.get("id", ""))
            node_doc_id = n.get("doc_id")
            # 推断这个节点的 doc_id（兼容历史节点 doc_id 字段缺失）
            inferred_doc_id = node_doc_id
            if not inferred_doc_id and node_id.startswith("doc_"):
                inferred_doc_id = node_id[len("doc_"):]
            if inferred_doc_id and inferred_doc_id not in live_doc_ids:
                ghost_ids.add(node_id)
                details.append({"id": node_id, "name": n.get("name"), "doc_id": inferred_doc_id})

        new_nodes = [n for n in self._graph.get("nodes", []) if n["id"] not in ghost_ids]
        new_edges = [
            e for e in self._graph.get("edges", [])
            if e.get("source") not in ghost_ids
            and e.get("target") not in ghost_ids
        ]

        removed_nodes = before_nodes - len(new_nodes)
        removed_edges = before_edges - len(new_edges)

        self._graph["nodes"] = new_nodes
        self._graph["edges"] = new_edges
        if removed_nodes or removed_edges:
            self._save_graph()

        return {
            "removed_nodes": removed_nodes,
            "removed_edges": removed_edges,
            "remaining_nodes": len(new_nodes),
            "remaining_edges": len(new_edges),
            "details": details,
        }

    def rebuild_from_documents(self, doc_id: str, title: str, content: str) -> dict:
        """从备份重建图谱关联（用于回收站恢复后）"""
        return self.build_from_document(doc_id, title, content)

    def get_node_count(self) -> dict:
        """获取节点和边的数量统计"""
        return {
            "nodes": len(self._graph.get("nodes", [])),
            "edges": len(self._graph.get("edges", [])),
        }
    
    def get_node_detail(self, node_id: str) -> Optional[dict]:
        """获取节点详情及关联关系"""
        node = None
        for n in self._graph["nodes"]:
            if n["id"] == node_id:
                node = n
                break
        
        if not node:
            return None
        
        # 获取关联的边
        related_edges = []
        for edge in self._graph["edges"]:
            if edge["source"] == node_id or edge["target"] == node_id:
                related_edges.append(edge)
        
        # 获取关联的节点
        related_nodes = []
        related_ids = set()
        for edge in related_edges:
            related_ids.add(edge["source"])
            related_ids.add(edge["target"])
        
        for n in self._graph["nodes"]:
            if n["id"] in related_ids and n["id"] != node_id:
                related_nodes.append(n)
        
        return {
            "node": node,
            "edges": related_edges,
            "related_nodes": related_nodes
        }
    
    def search_subgraph(self, query: str, depth: int = 2) -> dict:
        """搜索子图谱（任务 A：拆词匹配，支持多关键词 query）"""
        # 拆词（支持中英文空格/逗号/顿号分隔），任一词命中即匹配
        keywords = [w for w in re.split(r"[\s,，、]+", query) if w]
        if not keywords:
            keywords = [query]
        keywords_lower = [k.lower() for k in keywords]
        matched_nodes = []
        for node in self._graph["nodes"]:
            text = (node["name"] + " " + node.get("description", "")).lower()
            if any(kw in text for kw in keywords_lower):
                matched_nodes.append(node)
        
        if not matched_nodes:
            return {"nodes": [], "edges": []}
        
        # BFS 扩展邻居
        result_nodes = {n["id"]: n for n in matched_nodes}
        result_edges = []
        
        for _ in range(depth):
            current_ids = set(result_nodes.keys())
            new_ids = set()
            
            for edge in self._graph["edges"]:
                if edge["source"] in current_ids or edge["target"] in current_ids:
                    result_edges.append(edge)
                    new_ids.add(edge["source"])
                    new_ids.add(edge["target"])
            
            for nid in new_ids:
                if nid not in result_nodes:
                    for node in self._graph["nodes"]:
                        if node["id"] == nid:
                            result_nodes[nid] = node
                            break
        
        return {
            "nodes": list(result_nodes.values()),
            "edges": result_edges
        }
    
    def hybrid_search(self, query: str, documents: List[dict]) -> dict:
        """混合检索：图谱 + 文本"""
        # 图谱检索
        graph_results = self.search_subgraph(query, depth=1)
        
        # 文本检索（简单关键词匹配）
        text_results = []
        query_lower = query.lower()
        for doc in documents:
            score = 0
            content_lower = doc.get("content", "").lower()
            if query_lower in content_lower:
                score = content_lower.count(query_lower) / len(content_lower.split())
            if score > 0:
                text_results.append({
                    "document": doc,
                    "score": score,
                    "type": "text"
                })
        
        text_results.sort(key=lambda x: x["score"], reverse=True)
        
        return {
            "graph": graph_results,
            "text": text_results[:10],
            "sources": "hybrid"
        }


# 全局实例
kg_service = KnowledgeGraphService()

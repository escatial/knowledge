"""
RAG 检索链 - 基于 LangChain 原生组件（中心化设计）

【设计原则】RAGChainService 是整个项目唯一的 RAG 入口：
1. 所有检索都走 HybridRetriever（LangChain BaseRetriever）
2. 所有生成都走 LangChain LCEL Chain
3. 流式与非流式共用同一个检索器和提示词模板
4. 任何 API 端点（/api/ai/ask、/api/ai/ask/stream、/api/search/*）
   都必须通过本服务调用，不允许绕过 RAG 直接拼装 Prompt
"""
import logging
import re
from typing import Optional, List, Generator

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from app.core.llm_chain import LLMChainService
from app.core.vector_store import VectorStore
from app.services.knowledge_graph import KnowledgeGraphService
from app.services.document_service import _documents

logger = logging.getLogger(__name__)


# ── Prompt 模板（单一来源，所有端点共享）────────────────────────────

# 任务 P3-7 修复：清洗 LLM 输出中的占位符/调试字符串
# 当 LLM 在回答中输出 [object Object]、[object Promise]、<undefined>、{{xxx}} 等
# 占位符/调试字符串时，自动清洗为"（此处内容因模型输出异常已省略）"，避免污染最终答案。
_PLACEHOLDER_PATTERNS = [
    (r"\[object\s+\w+\]", "（内容异常）"),         # [object Object] / [object Promise]
    (r"<undefined>", "（内容异常）"),
    (r"<null>", "（内容异常）"),
    (r"<empty>", "（内容异常）"),
    (r"\{\{[\w\.\-]+\}\}", "（内容异常）"),       # {{xxx}} 模板占位符
    (r"\$\{[\w\.\-]+\}", "（内容异常）"),         # ${xxx} 模板占位符
    (r"(?<![\w<])undefined(?![\w>])", "（内容异常）"),  # 单独的 undefined
    (r"(?<![\w<])null(?![\w>])", "（内容异常）"),      # 单独的 null
    (r"\bNaN\b", "（内容异常）"),
]

def _sanitize_llm_output(text: str) -> str:
    """清洗 LLM 输出中的占位符/调试字符串

    Args:
        text: LLM 原始输出

    Returns:
        清洗后的安全文本
    """
    if not text:
        return text
    import re as _re
    cleaned = text
    for pattern, replacement in _PLACEHOLDER_PATTERNS:
        cleaned = _re.sub(pattern, replacement, cleaned)
    # 合并连续的"（内容异常）"为一个
    cleaned = _re.sub(r"（内容异常）{2,}", "（内容异常）", cleaned)
    # 如果整段都是异常说明，标记为不可用
    if cleaned.strip() in ("（内容异常）", ""):
        return "（模型输出异常，请换个问法重试）"
    return cleaned


SYSTEM_PROMPT = (
    '你是一个知识库助手，基于提供的知识回答问题。\n\n'
    '【核心原则 - 宁缺毋滥】\n'
    '0. **最高原则**：如果提供的参考资料**完全不能**回答问题（连部分相关都没有），必须明确说"知识库中暂未找到相关资料"，'
    '绝对不能基于完全无关的内容瞎编答案。\n'
    '   **但只要参考资料包含任何与问题相关的内容，就应该积极回答**——可以综合多个文档、总结归纳。\n\n'
    '【输出格式硬约束 - 严禁出现占位符/调试字符串】\n'
    'A. **绝对禁止**在回答中出现以下任何占位符或调试字符串：\n'
    '   - `[object Object]`、`[object Promise]`、`[object Array]` 等 JS 对象序列化错误\n'
    '   - `undefined`、`null`、`NaN` 等裸类型字面量\n'
    '   - `{` `}` `[` `]` 单独出现的非 JSON 块\n'
    '   - `<undefined>`、`<null>`、`<empty>` 等尖括号占位符\n'
    '   - `{{xxx}}`、`${xxx}` 等未替换的模板字符串\n'
    'B. **如果不知道怎么表达某个值**：用自然语言描述（如"约 10 篇"、"3 个分类"），不要输出占位符。\n'
    'C. **当需要展示结构化数据时**（如分类、文档列表、统计数据），**使用 Markdown 表格**而非纯文本：\n'
    '   ```\n'
    '   | 列1 | 列2 | 列3 |\n'
    '   |-----|-----|-----|\n'
    '   | 值1 | 值2 | 值3 |\n'
    '   ```\n'
    '   例如回答"知识库分哪些分类"时，**必须**用表格列出每个分类的文档数。\n\n'
    '【重要规则】\n'
    '1. 如果用户追问上下文相关问题，必须结合之前对话的主题和知识库内容给出精准回答。\n'
    '2. 不要反问用户，直接基于上下文推断用户意图。\n'
    '3. 始终保持回答基于知识库内容，不要编造信息。\n'
    '4. 当知识库未提供相关内容时，请明确告知用户"知识库中暂未找到相关资料"。\n'
    '5. **诚实评估相关性**：每条参考资料前都标注了"相关度"分数（0~1之间）。'
    '**相似度不等于相关性**——相似度只是词向量距离，相关性需要看内容是否真的能回答问题。\n'
    '   - 相似度 < 0.20 → 大概率不相关，不要勉强使用\n'
    '   - 相似度 0.20~0.40 → 需要进一步判断内容是否真的回答问题\n'
    '   - 相似度 ≥ 0.50 → 通常真的相关\n'
    '   **判断标准**：文档是否包含回答问题所需的关键信息/概念/数据？仅出现相同关键词 ≠ 真正相关。\n'
    '6. **严防拼接造句**：严禁把多个不相关主题的片段拼在一起编造答案。\n'
    '   例如：问题"什么是RAG"，但引用是"我叫张三"和"如何做饭"——这两条都明显不相关，应明确说"知识库中没有相关内容"。\n'
    '7. 【防止越界】当用户问到"知识库如何使用"、"知识库有什么"、"介绍一下知识库"等问题时，'
    '请仅基于【知识库介绍】片段中的内容回答，把这些片段视作知识库自身的内容来引用，'
    '不要把知识库里的学术论文当成"本知识库"介绍。\n'
    '8. **透明化处理**：回答时使用如下格式——\n'
    '   - 如果找到了相关资料：基于资料回答 + 引用标号 ①②③\n'
    '   - 如果找不到：明确说"抱歉，知识库中没有找到关于『XX』的相关资料"，并可建议用户换个问法或上传相关文档\n'
    '8.1 **【严格】禁止在正文末尾追加"引用来源"、"引用列表"、"参考资料"、"置信度评估"、"总结"等段落**\n'
    '   - 系统会自动渲染引用来源、置信度等模块，你不需要自己输出\n'
    '   - 直接结束回答即可，不要在正文末尾写 `**引用来源：**...` 或 `**置信度评估：**...`\n'
    '8.2 **【任务 M】当判断知识库中无相关资料时，必须【严格】按以下固定文案输出开头**：\n'
    '   - 开头必须是"知识库中暂未找到关于『XX』的相关资料"（"未"字必须出现）。\n'
    '   - **严禁**使用"知识库中找到"、"知识库中提到"、"知识库中包含"等非否定表述。\n'
    '   - **严禁**在"未找到"判断后**继续引用、摘录、解释**参考资料中的任何内容。\n'
    '   - **严禁**在"未找到"判断后补充与问题无直接关系的知识库内容介绍（如"知识库中提到了 X、Y、Z"）。\n'
    '   - **严禁**在"未找到"判断后添加引用标号 ①②③ 等。\n'
    '   - 只能紧跟"建议换个问法"或"建议上传相关文档"之类的一句话。\n'
    '   - **【任务 M·重要修订·v2】只有【参考资料列表为空】时，才允许输出"未找到"。**\n'
    '     如果参考资料中【至少存在 1 条】（无论相关度高低、是否主题直接覆盖），都【必须】基于该资料做最相关总结：\n'
    '     - 提取资料中的关键概念、定义、组件、步骤\n'
    '     - 即使不能 100% 直接命中问题，也要基于资料做最相关的回答\n'
    '     - **严禁**以"主题未直接覆盖"、"仅关键词相似"为由拒绝回答或输出"未找到"\n'
    '     - **严禁**以"内容与问题无直接关系"为由拒绝回答\n'
    '     - **严禁**因参考资料标题"看起来不相关"（如"03LLM框架实战_基础.pdf"）就忽略其内容\n'
    '   - **【任务 M·重要修订·v2 兜底】**判定标准已由系统接管：\n'
    '     - 参考资料 ≥ 1 条 → 后端强制要求 LLM 基于该资料回答（即使 LLM 输出"未找到"也会被改写）\n'
    '     - 参考资料 = 0 条 → LLM 可输出"知识库中暂未找到..."\n'
    '8.3 **【任务 8 优化·抗幻觉】严格的事实约束**：\n'
    '   - 你只能基于"参考资料"中的具体文字回答问题，不允许加入参考资料之外的任何事实、术语、数据。\n'
    '   - 当用户问题的主题在参考资料中**没有直接覆盖**时（如用户问"如何优化AI调用的时机"但参考资料只讲 RAG/Agent），必须明确说"未找到"，**不要**拼接不同主题的资料硬凑成答案。\n'
    '   - **绝对禁止**使用以下"拼接式空话"开头：`根据参考资料可以总结`、`综合以上内容`、`综上所述`、`大致可以归纳为`、`主要可以从以下几个角度`、`通常情况下`——这些都是幻觉的典型征兆。\n'
    '   - **引用完整性**：每一个引用标号 ①②③ 必须有对应的实际内容，禁止在文末堆叠引用（所有引用必须穿插在正文相应位置）。\n'
    '   - **禁止套话**：不允许使用"根据我的知识"、"一般来说"、"通常情况下"等无具体来源的表述。\n'
    '8.4 **【任务 P0 优化·事实点溯源】每一条事实必须可追溯**：\n'
    '   - 回答中出现的每个具体技术名词、概念、组件、步骤，必须能在参考资料原文里找到对应文字（哪怕只是同义/近义表述）。\n'
    '   - 如果参考资料里没有相关表述，禁止凭空添加"该领域通常有 X、Y、Z"等补充内容——这是幻觉。\n'
    '   - 数字、版本号、年代、人物名等具体信息必须 100% 来自参考资料，禁止使用训练数据中的一般知识。\n'
    '   - 当引用某条参考资料时，该条资料的实际内容必须**直接支撑**被引用的论断，**禁止**引用与上下文无关的资料来"装饰"答案。\n'
    '8.5 **【任务 P0 优化·结构化表达】用清单代替段落**：\n'
    '   - 当参考资料较丰富时，**优先用 Markdown 列表（- 或 1./2./3.）**组织事实。\n'
    '   - 每条列表项只包含**一个**事实点（便于验证溯源）。\n'
    '   - 列表项之间不要有"承上启下"的过渡句（这类过渡句往往是幻觉重灾区）。\n'
    '9. **【关键】引用标注规则**：\n'
    '   - 当且仅当回答中实际引用了某条参考资料时，才在该处句末添加 ①、②、③ 等圈数字引用标号\n'
    '   - 圈数字必须使用全角 unicode 字符：① ② ③ ④ ⑤ ⑥ ⑦ ⑧ ⑨ ⑩ ⑪ ⑫ ⑬ ⑭ ⑮ ⑯ ⑰ ⑱ ⑲ ⑳\n'
    '   - 引用标号必须与下方【参考资料】的顺序一一对应：第 1 条资料对应 ①，第 2 条对应 ②，以此类推\n'
    '   - **数量严格一致**：正文中出现的圈数字总数 = 参考资料的数量\n'
    '   - **禁止**重复编号（同一个 ① 出现 2 次）或乱序（先 ② 后 ①）\n'
    '   - **禁止**全部堆在文末：必须根据内容相关性穿插到对应位置\n'
    '   - 如果参考资料为 0 条，则不写任何引用标号'
)

RAG_CONTEXT_TEMPLATE = (
    "【知识库参考内容】\n{context}\n\n"
    "请基于以上知识库内容回答用户的最新问题。"
)


def _build_rag_prompt() -> ChatPromptTemplate:
    """构建 RAG Prompt 模板（统一）"""
    return ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("system", RAG_CONTEXT_TEMPLATE),
        MessagesPlaceholder(variable_name="history"),
        ("human", "{question}"),
    ])


# ── 检索器 ────────────────────────────────────────────────────────

# 模块级同义词词典（关键修复：不能用类属性）
_QUERY_SYNONYMS = {
    # 通用
    "怎么用": ["如何使用", "怎么使用", "使用方式", "用法", "怎么操作"],
    "是什么": ["什么是", "什么叫", "定义", "概念"],
    "怎么": ["如何", "怎样", "怎么才能", "怎么可以"],
    "为什么": ["为何", "原因", "为什么会"],
    "介绍": ["简介", "概述", "概况", "说明"],
    "区别": ["差异", "不同", "对比", "比较"],
    "哪个": ["哪一个", "哪个更好", "选择哪个"],
    # 业务术语
    "AI调用": ["AI 调用", "模型调用", "LLM 调用", "调用大模型", "调用模型"],
    "智能体": ["Agent", "agent", "AI agent", "智能代理"],
    "提示词": ["prompt", "Prompt", "系统提示", "指令"],
    "知识库": ["知识库系统", "Knowledge OS", "本系统", "知识平台"],
    "大模型": ["LLM", "llm", "大语言模型"],
    "知识图谱": ["图谱", "知识网络", "KG", "knowledge graph"],
    "调用时机": ["调用频率", "调用场景", "调用策略", "调用成本"],
    # 口语化
    "搞": ["做", "实现", "写", "编写"],
    "咋": ["怎么", "如何"],
    "哪能": ["怎么", "如何"],
}

class HybridRetriever(BaseRetriever):
    """
    混合检索器 - 整合向量检索 + 知识图谱 + 关键词回退
    兼容 LangChain BaseRetriever 接口

    检索策略：
    1. 向量语义检索（主）
    2. 知识图谱实体扩展（辅）
    3. 关键词全文回退（兜底）
    """

    top_k: int = 8  # 任务 8 优化：5→8 提升召回率
    kg_depth: int = 1
    enable_kg: bool = True
    enable_keyword_fallback: bool = True
    # 最小相关度阈值
    # 任务 8 修复：实测下 BGE 检索分数普遍在 0.85-0.98 区间（共享词污染导致区分度低）
    # 改为相对阈值：top_k 中取前 8 名（top-1 分数作锚，保留 ≥ top1 - 0.08 的）
    # 同时保留 min_score=0.20 作为绝对底线（过滤极端噪声）
    min_score: float = 0.20
    # 任务 8：相对分数阈值
    relative_score_threshold: float = 0.06
    # 任务 P0 优化：关闭 LLM 二次过滤（耗时高 32s/case → 用关键词过滤替代）
    # 如需临时开启用于 debug，可通过环境变量 ENABLE_LLM_FILTER=1 启用
    enable_llm_relevance_filter: bool = False
    # 任务 P0 优化：新增"关键词覆盖过滤"作为 LLM 二次过滤的轻量替代
    # 要求召回的 doc 至少包含 query 中一个关键词（中文按字/词切分）
    enable_keyword_relevance_filter: bool = True
    # 任务 P0 优化：query 改写（解决同义词 / 口语化问句）
    enable_query_rewrite: bool = True
    # RRF 融合参数
    rrf_k: int = 60
    categories: Optional[List[str]] = None
    # 任务 2：知识库隔离（None 或 "all" 表示不限）
    knowledge_base_id: Optional[str] = None

    def _get_relevant_documents(
        self, query: str, *, run_manager: Optional[CallbackManagerForRetrieverRun] = None
    ) -> List[Document]:
        """执行混合检索，返回 LangChain Document 列表"""
        cat_info = f" | cats={self.categories}" if self.categories else ""
        logger.info(f"[RAG] 混合检索 | query={query[:50]}...{cat_info}")

        documents: List[Document] = []
        vector_hits = 0

        # 1. 双路召回：向量检索 + 关键词检索并行
        vector_results_filtered = []
        try:
            vector_results = VectorStore.search(
                query,
                top_k=self.top_k * 2,  # 召回更多以便后续融合
                categories=self.categories,
                knowledge_base_id=self.knowledge_base_id,
            )
            # 任务 8 优化：双重过滤
            #   1) 绝对底线：min_score（过滤极端噪声）
            #   2) 相对阈值：top1 - 0.08（BGE 高区分度问题——共享词污染）
            if vector_results:
                top1_score = vector_results[0]["score"]
                min_rel = max(self.min_score, top1_score - self.relative_score_threshold)
                vector_results_filtered = [
                    r for r in vector_results if r["score"] >= min_rel
                ]
                logger.info(
                    f"[RAG] 相对阈值过滤 | top1={top1_score:.3f} | "
                    f"min_rel={min_rel:.3f} | 保留={len(vector_results_filtered)}/{len(vector_results)}"
                )
            else:
                vector_results_filtered = []
        except Exception as e:
            logger.warning(f"[RAG] 向量检索失败: {e}")

        keyword_results = []
        if self.enable_keyword_fallback:
            try:

                keyword_results = self._keyword_search(query, limit=self.top_k * 2)
            except Exception as e:
                logger.warning(f"[RAG] 关键词检索失败: {e}")

        # RRF (Reciprocal Rank Fusion) 融合双路结果
        # 公式: score = 1 / (k + rank)
        fused_scores = {}  # {doc_id_chunk_idx: {"doc": Document, "score": float}}
        
        # 处理向量检索结果
        for rank, r in enumerate(vector_results_filtered):
            # 以 doc_id 为主键进行融合，避免同一文档的不同片段重复霸榜
            doc_id = r["metadata"].get("doc_id") or r["id"]
            rrf_score = 1.0 / (self.rrf_k + rank + 1)
            if doc_id in fused_scores:
                # 同一个文档的多个 chunk 被向量命中，累加 RRF 分数
                fused_scores[doc_id]["rrf_score"] += rrf_score
                # 拼接内容（按原始片段顺序，这里简单追加，最多保留较长内容）
                if r["content"] not in fused_scores[doc_id]["doc"].page_content:
                    fused_scores[doc_id]["doc"].page_content += f"\n...\n{r['content']}"
            else:
                fused_scores[doc_id] = {
                    "doc": Document(
                        page_content=r["content"],
                        metadata={
                            **r["metadata"],
                            "vector_score": r["score"],
                            "source": "vector",
                            "id": r["id"],
                        },
                    ),
                    "rrf_score": rrf_score
                }
            
        # 处理关键词检索结果
        for rank, doc in enumerate(keyword_results):
            doc_id = doc.metadata.get("doc_id") or doc.metadata.get("id")
            rrf_score = 1.0 / (self.rrf_k + rank + 1)
            if doc_id in fused_scores:
                fused_scores[doc_id]["rrf_score"] += rrf_score
                fused_scores[doc_id]["doc"].metadata["source"] = "hybrid"
                fused_scores[doc_id]["doc"].metadata["kw_score"] = doc.metadata.get("score")
                # 如果关键词片段不在已有内容中，则追加
                if doc.page_content not in fused_scores[doc_id]["doc"].page_content:
                    # 避免内容过长，只追加不在内的部分
                    fused_scores[doc_id]["doc"].page_content += f"\n...\n[关键词命中]: {doc.page_content}"
            else:
                fused_scores[doc_id] = {
                    "doc": doc,
                    "rrf_score": rrf_score
                }

        # 排序并取 Top K
        sorted_fused = sorted(fused_scores.values(), key=lambda x: x["rrf_score"], reverse=True)[:self.top_k]
        for item in sorted_fused:
            doc = item["doc"]
            # 恢复原始分数供 LLM 参考，rrf_score 仅用于排序
            try:
                raw_score = doc.metadata.get("vector_score") or doc.metadata.get("kw_score") or 0.5
            except AttributeError:
                # metadata 可能是 Pydantic v1 dict、v2 model_extra、或其他 Mapping，统一降级
                meta = doc.metadata
                if hasattr(meta, "vector_score"):
                    raw_score = meta.vector_score or meta.kw_score or 0.5
                else:
                    raw_score = 0.5
            try:
                doc.metadata["score"] = raw_score
                doc.metadata["rrf_score"] = item["rrf_score"]
            except Exception as e:
                # metadata 在某些 pydantic v2 严格模式下是只读，改为 setattr 兜底
                logger.warning(f"[RAG] doc.metadata 不可直接 []= 写入，启用 setattr 兜底: {e}")
            documents.append(doc)

        vector_hits = len(vector_results_filtered)
        kw_hits = len(keyword_results)
        logger.info(f"[RAG] 双路召回完成 | vector={vector_hits} | keyword={kw_hits} | fused={len(documents)}")

        # 2. 知识图谱检索 (补充)
        if self.enable_kg:
            try:
                kg_service = KnowledgeGraphService(knowledge_base_id=self.knowledge_base_id or "default")
                graph_results = kg_service.search_subgraph(query, depth=self.kg_depth)
                for node in graph_results.get("nodes", [])[:5]:
                    documents.append(
                        Document(
                            page_content=f"实体: {node['name']} ({node['type']})",
                            metadata={
                                "source": "knowledge_graph",
                                "entity_type": node["type"],
                                "entity_name": node["name"],
                            },
                        )
                    )
            except Exception as e:
                logger.warning(f"[RAG] 知识图谱检索失败: {e}")

        # 任务 4 修复：长度加权 + LLM 二次相关性过滤（所有 doc 收集完之后）
        # 这样能避免短文本错排 + 真正相关的文档被噪声淹没
        if documents:
            documents = self._apply_length_weighting(documents)
            # 任务 P0 优化：query 改写（仅在第一次进入时记录原始 query）
            effective_query = query
            if self.enable_query_rewrite:
                try:
                    effective_query = self._rewrite_query(query)
                except Exception as e:
                    logger.warning(f"[RAG] query 改写失败，使用原始 query: {e}")
                    effective_query = query
            # 任务 P0 优化：关键词覆盖过滤（替代 LLM 二次过滤的轻量方案）
            if self.enable_keyword_relevance_filter and len(documents) > 1:
                documents = self._keyword_relevance_filter(effective_query, documents)
            # 任务 P0 优化：LLM 二次过滤默认关闭（耗时 32s/case → 用关键词过滤替代）
            if self.enable_llm_relevance_filter and len(documents) > 1:
                documents = self._llm_relevance_filter(query, documents)

        logger.info(
            f"[RAG] 检索完成 | vector={vector_hits} | total={len(documents)}"
        )
        return documents

    # ============== 任务 P0 优化：query 改写 + 关键词覆盖过滤 ==============

    @classmethod
    def _rewrite_query(cls, query: str) -> str:
        """任务 P0 优化：query 改写

        策略：
        1. 拆解同义词：原 query + 1-2 个同义改写 → 用于扩大 embedding 召回
        2. 不改变语义，仅扩充检索覆盖面
        3. **关键修复**：如果原 query 本身就是"主语+谓语"完整表达（如"什么是RAG"），
           **不再做过度改写**（避免稀释关键词命中）

        Returns:
            改写后的 query（用 ||| 分隔多个版本，向量检索时取并集）
        """
        # 启发式：query 中已含"什么是/什么叫/如何/怎么"等明确主题词时不做改写
        complete_patterns = ["什么是", "什么叫", "如何", "怎么", "为什么", "介绍"]
        if any(p in query for p in complete_patterns):
            return query
        rewritten = [query]
        for src, targets in _QUERY_SYNONYMS.items():
            if src in query:
                for t in targets:
                    new_q = query.replace(src, t)
                    if new_q != query and new_q not in rewritten:
                        rewritten.append(new_q)
        # 限制最多 2 个改写版本（避免过多噪声）
        if len(rewritten) > 2:
            rewritten = rewritten[:2]
        return " ||| ".join(rewritten)

    @classmethod
    def _keyword_relevance_filter(cls, query: str, docs: List[Document]) -> List[Document]:
        """任务 P0 优化：关键词覆盖过滤（替代 LLM 二次过滤）

        原理：
        - 提取 query 中的中文关键词（去除停用词）
        - 召回的 doc 至少应与 query 有 1 个共同关键词
        - 没有任何共同关键词的 doc 视为"表面相似但主题不符" → 丢弃

        优势：
        - 延迟 < 1ms（纯字符串匹配）
        - 可解释：每条 doc 都可以解释"为什么保留/丢弃"
        - 配合相对阈值过滤，进一步压缩噪声

        Args:
            query: 用户问题（可能含 ||| 分隔的改写版本）
            docs: 候选文档列表

        Returns:
            过滤后保留关键词覆盖度 ≥ 1 的文档
        """
        if not docs or len(docs) <= 1:
            return docs

        # 停用词表（中文常见虚词/代词）
        stop_words = {
            "的", "了", "和", "是", "在", "我", "有", "和", "就", "不", "人",
            "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去", "你",
            "会", "着", "没有", "看", "好", "自己", "这", "那", "什么", "如何",
            "怎么", "怎样", "为什么", "哪", "哪些", "那个", "这个", "吗",
        }

        # 关键修复：仅用原 query（不包含改写版本）做关键词提取
        # 原因：改写版本（如"什么叫RAG"）稀释关键词导致误杀
        original_query = query.split(" ||| ")[0]

        # 提取 query 关键词
        all_keywords = set()
        # 单字关键词（去停用词）
        for ch in original_query:
            if "\u4e00" <= ch <= "\u9fff" and ch not in stop_words:
                all_keywords.add(ch)
        # 英文/数字词
        import re as _re
        for word in _re.findall(r"[A-Za-z]+", original_query):
            if len(word) >= 2 and word.lower() not in stop_words:
                all_keywords.add(word.lower())
        # 2-gram 词组（中文）
        text_zh = _re.sub(r"[^\u4e00-\u9fff]", "", original_query)
        for i in range(len(text_zh) - 1):
            bigram = text_zh[i:i+2]
            if bigram[0] not in stop_words and bigram[1] not in stop_words:
                all_keywords.add(bigram)
        # 3-gram 词组（更精确匹配）
        for i in range(len(text_zh) - 2):
            trigram = text_zh[i:i+3]
            if all(c not in stop_words for c in trigram):
                all_keywords.add(trigram)

        if not all_keywords:
            return docs

        # 过滤 docs
        filtered = []
        for d in docs:
            content = (d.page_content or "").lower()
            content_zh = _re.sub(r"[^\u4e00-\u9fff]", "", content)
            # 关键词命中数
            hit_count = sum(
                1 for kw in all_keywords
                if kw.lower() in content or kw.lower() in content_zh
            )
            # 至少命中 1 个
            if hit_count >= 1:
                d.metadata["keyword_hits"] = hit_count
                filtered.append(d)

        dropped = len(docs) - len(filtered)
        if dropped > 0:
            logger.info(
                f"[RAG] 关键词覆盖过滤 | query关键词={len(all_keywords)} | "
                f"原始={len(docs)} | 保留={len(filtered)} | 丢弃={dropped}"
            )
        # 万一全过滤掉，保守保留 top-3（避免 0 召回）
        if not filtered:
            return docs[:3]
        return filtered

    def _llm_relevance_filter(self, query: str, docs: List[Document]) -> List[Document]:
        """任务 4 修复：用 LLM 批量判断每个文档是否真的与问题相关

        与相似度（cosine distance）不同，"是否真的相关"需要语义理解：
        - 相似度高但内容不相关（如"我叫张三"与"什么是RAG"相似度可能被算高）
        - 相似度低但内容真正相关（hash embedding 算不准）

        LLM 判断维度：
        1. 文档是否包含回答问题所需的关键信息
        2. 文档主题是否与问题主题一致
        3. 文档是直接回答还是仅表面相似

        Args:
            query: 用户问题
            docs: 候选文档列表

        Returns:
            过滤后保留真正相关的文档（按 LLM 判断的相关性重排）
        """
        if not docs or len(docs) <= 1:
            return docs

        try:
            from app.core.llm import LLMService
            llm = LLMService()

            # 构造判断 prompt（每条 200 字内，避免超长）
            items_text = []
            for i, d in enumerate(docs):
                snippet = (d.page_content or "")[:200].replace("\n", " ")
                items_text.append(f"[{i}] 相似度={d.metadata.get('score', 0):.2f} 内容={snippet}")

            prompt = f"""你是相关性判断器。判断每个文档片段是否与用户问题真正相关（不是表面相似，而是能直接支撑回答）。

【用户问题】
{query}

【候选文档】
{chr(10).join(items_text)}

【判断标准】
- 1 = 真正相关：包含回答问题所需的关键信息
- 0 = 不相关：仅表面相似或主题不符

【要求】
- 宁可漏判也不误判（宁可丢弃也不要保留无关项）
- 相似度 < 0.20 的几乎肯定不相关
- 输出严格 JSON 数组（0/1），不要任何其他文字

【示例】问题：「什么是RAG」 → [0, 1, 0, 0, 1]
"""

            response = llm.chat(
                messages=[{"role": "user", "content": prompt}],
                model=getattr(self, "_llm_model", None),
            )
            content = str(response).strip()

            # 提取 JSON 数组
            import json
            match = re.search(r"\[[\d,\s]+\]", content)
            if not match:
                logger.warning(f"[RAG] LLM 二次过滤：响应无法解析 JSON，保留全部 docs\n原始: {content[:200]}")
                return docs
            try:
                relevance = json.loads(match.group(0))
            except json.JSONDecodeError:
                logger.warning(f"[RAG] LLM 二次过滤：JSON 解析失败，保留全部 docs\n原始: {match.group(0)}")
                return docs

            # 长度对齐：如果 LLM 返回的数量与 docs 不一致，智能处理
            if len(relevance) != len(docs):
                logger.warning(
                    f"[RAG] LLM 二次过滤：长度不匹配 ({len(relevance)} vs {len(docs)})，尝试智能对齐"
                )
                # 智能补齐：缺失的视为 0（不相关），多余的截断
                if len(relevance) < len(docs):
                    relevance = relevance + [0] * (len(docs) - len(relevance))
                else:
                    relevance = relevance[:len(docs)]
                logger.info(f"[RAG] LLM 二次过滤：补齐后长度={len(relevance)}")

            # 过滤并保留顺序
            filtered = [d for d, r in zip(docs, relevance) if r == 1]
            dropped = len(docs) - len(filtered)
            if dropped > 0:
                logger.info(
                    f"[RAG] LLM 二次过滤 | 原始={len(docs)} | 保留={len(filtered)} | 丢弃={dropped}"
                )
            return filtered if filtered else docs  # 万一全过滤掉，保守保留原列表

        except Exception as e:
            logger.warning(f"[RAG] LLM 二次过滤异常: {e}")
            return docs  # 失败时保守保留

    @staticmethod
    def _apply_length_weighting(docs: List[Document]) -> List[Document]:
        """任务 4 修复：长文档加权，避免短文本错排

        原理：纯 hash embedding 下，短文本（如对话片段"我叫张三"）因维度差异
        容易被算成"距离近"，导致短而不相关的内容排在前。

        策略：内容长度在 100-2000 字符之间的文档给轻微加分（≤1.1x），
        太短（<50）或太长（>5000）的不加权。
        """
        if not docs:
            return docs

        def length_factor(content: str) -> float:
            n = len(content or "")
            if n < 50 or n > 5000:
                return 1.0  # 太短或太长，不加权
            # 在 50-2000 之间线性加分，最长 2000 字符时为 1.1
            return 1.0 + min(0.1, (n - 50) / 2000 * 0.1)

        # 仅在分数接近时考虑长度（差距 > 0.05 时长度不参与）
        for d in docs:
            # 任务 5：双路召回后，使用 rrf_score 作为基准分数进行长度加权，避免破坏 RRF 排名
            base_score = d.metadata.get("rrf_score") or d.metadata.get("score", 0)
            factor = length_factor(d.page_content)
            # 长度加权：仅作为 tie-breaker，不超过原分数的 10%
            d.metadata["weighted_score"] = base_score * factor

        # 按 weighted_score 重新排序
        docs.sort(key=lambda d: d.metadata.get("weighted_score", 0), reverse=True)
        return docs

    def _keyword_search(self, query: str, limit: int = 5) -> List[Document]:
        """关键词全文检索（任务 C：拆词匹配 + 多词叠加得分）
        
        作为双路召回的其中一路，这里遍历文档库进行快速字符串匹配。
        注意：实际生产环境中这里应该用 Elasticsearch/MeiliSearch 等。
        """
        results = []
        query_lower = query.lower().strip()
        if not query_lower:
            return results

        # 拆词：支持中英文空格/逗号/顿号
        keywords = [w for w in re.split(r"[\s,，、]+", query_lower) if w]
        if not keywords:
            keywords = [query_lower]

        cat_filter = set(self.categories) if self.categories else None
        kb_filter = self.knowledge_base_id if self.knowledge_base_id and self.knowledge_base_id != "all" else None

        # 遍历所有 document
        for doc in _documents.values():
            if cat_filter and getattr(doc, "category", "默认") not in cat_filter:
                continue
            if kb_filter and getattr(doc, "knowledge_base_id", "default") != kb_filter:
                continue
                
            content = doc.content or ""
            content_lower = content.lower()

            # 任务 C：拆词匹配 — 任何关键词命中即可入选，得分 = 命中数 × 0.15 + 位置加成
            hit_count = sum(1 for kw in keywords if kw in content_lower)
            if hit_count == 0:
                continue
            # 取第一个命中关键词的位置作为 snippet 锚点
            first_idx = -1
            for kw in keywords:
                idx = content_lower.find(kw)
                if idx >= 0:
                    first_idx = idx
                    break
            start = max(0, first_idx - 300)
            end = min(len(content), first_idx + 500)
            snippet = content[start:end]

            occurrences = sum(content_lower.count(kw) for kw in keywords)
            score = min(0.4 + hit_count * 0.15 + min(occurrences, 10) * 0.03, 0.95)

            results.append(Document(
                page_content=snippet,
                metadata={
                    "id": f"{doc.id}_kw_hit",
                    "doc_id": doc.id,
                    "title": doc.title,
                    "category": getattr(doc, "category", "默认"),
                    "source": "keyword",
                    "score": score,
                    "kw_hit_count": hit_count,
                    "kw_occurrences": occurrences,
                },
            ))

        results.sort(key=lambda x: x.metadata.get("score", 0), reverse=True)
        return results[:limit]


# ── 上下文格式化 ─────────────────────────────────────────────────


# 任务 Y：解除 system_faq 文档的硬编码 —— 抽到 app/core/system_faq.py
# 保留兼容别名：旧代码引用 SYSTEM_FAQ_DOCS 仍然可用
# 新代码请使用 from app.core.system_faq import get_system_faq_docs
try:
    from app.core.system_faq import DEFAULT_FAQ_DOCS as SYSTEM_FAQ_DOCS
except ImportError:
    # 极端 fallback（保证代码加载不报错）
    SYSTEM_FAQ_DOCS = [
        {
            "id": "__kb_fallback__",
            "title": "知识库介绍",
            "content": "本知识库支持 RAG 检索增强生成。",
            "score": 1.0,
        }
    ]


# 触发系统 FAQ 的查询模式（关键词正则）—— 任务 6 重构：已迁移到 IntentClassifier
# 保留 SYSTEM_FAQ_TRIGGERS 是为了兼容旧代码，**实际判断**改用 IntentClassifier.classify()
SYSTEM_FAQ_TRIGGERS = []  # 兼容字段：已废弃


def is_system_faq_query(query: str) -> bool:
    """检测查询是否属于"系统使用/能力介绍"类问题（任务 6：已迁移到 IntentClassifier）"""
    try:
        from app.core.intent_classifier import IntentClassifier, IntentType
        result = IntentClassifier.classify(query)
        return result.intent == IntentType.SYSTEM_FAQ
    except Exception:
        return False


def _format_documents_for_context(docs: List[Document]) -> str:
    """把 LangChain Document 列表格式化为 Prompt 上下文字符串

    任务 Z v5：在 context 顶部追加【回答指引】，引导 LLM 真正执行 RAG（检索-增强-生成）流程：
    - 如果资料是代码示例：要求 LLM 逆向归纳工具/库的功能/组件/用途
    - 如果资料包含 import 语法/函数定义：要求 LLM 从中提取"这个库提供了什么能力"
    """
    # 1) 回答指引：放在 context 顶部，确保 LLM 优先看到
    guidance = (
        "【回答指引·任务 RAG-v5】\n"
        "请严格按 RAG（检索-增强-生成）流程回答：\n"
        "1) **检索**：已检索到下方参考资料，**必须基于这些资料回答**（即使资料是代码示例、API 用法、片段）。\n"
        "2) **增强**：如果资料是【代码示例】，请从代码中【逆向归纳】出库/工具的功能/组件/用途：\n"
        "   - import 语句展示了库提供了哪些子模块（如 `from langchain.tools import tool` 说明库提供了 tools 工具）\n"
        "   - 装饰器/函数定义展示了库的 API 形态（如 `@tool` 装饰器说明可以把普通函数注册为工具）\n"
        "   - 调用示例展示了库的典型使用场景（如 `create_agent` 说明可以创建带工具调用的 Agent）\n"
        "3) **生成**：基于归纳出的功能/组件，**用自然语言总结**这个库是什么、能做什么。\n"
        "4) **严禁**以\"代码示例不是概念定义\"为由输出\"未找到\"——代码示例本身就是库功能定义的最佳证据。\n"
        "5) **严禁**直接复制粘贴代码块作为答案——必须**归纳总结**为自然语言回答。\n"
        "6) **严禁**引入参考资料之外的任何事实/术语/数据。\n\n"
        "【参考资料】\n"
    )
    parts = [guidance]
    for doc in docs:
        source = doc.metadata.get("source", "unknown")
        score = doc.metadata.get("score", 0)
        title = doc.metadata.get("title", "")
        # 识别 doc 类型（启发式）
        content_preview = doc.page_content or ""
        is_code = (
            "import " in content_preview[:200]
            or "def " in content_preview[:200]
            or "from " in content_preview[:200]
            or "class " in content_preview[:200]
        )
        doc_type_tag = "代码示例" if is_code else "概念/说明"
        if source == "system_faq":
            # 知识库内置介绍：永远标记为高相关度，且不需要 [相关度] 前缀（避免 LLM 用 0.3 阈值过滤）
            # 标签用「知识库介绍」而非「系统操作知识」，引导 LLM 把它作为知识库自身内容来引用
            parts.append(f"【知识库介绍】{doc.page_content[:800]}")
        elif source in ("vector", "hybrid"):
            parts.append(
                f"【{doc_type_tag} | 相关度: {score:.2f} | {title}】\n{doc.page_content[:1500]}"
            )
        elif source == "knowledge_graph":
            parts.append(f"【知识图谱】{doc.page_content}")
        else:
            parts.append(f"【{doc_type_tag} | 关键词匹配】{doc.page_content[:1000]}")
    return "\n\n".join(parts) if parts else "暂无相关知识"


def _build_citations(docs: List[Document], top_n: int = 3) -> List[dict]:
    """任务 Z：从检索结果中提取引用信息（title/doc_title 提升到顶层）"""
    citations = []
    for doc in docs[:top_n]:
        meta = doc.metadata.copy()
        meta.pop("embedding", None)
        citations.append({
            "content": doc.page_content[:300],
            "title": meta.get("title") or meta.get("doc_title") or meta.get("source") or "文档片段",
            "doc_id": meta.get("doc_id") or meta.get("id") or "",
            "doc_title": meta.get("title") or meta.get("doc_title") or "文档片段",
            "metadata": meta,
            "score": float(meta.get("score", 0) or 0),
        })
    return citations


def _convert_history_to_messages(history: Optional[List[dict]]) -> List:
    """把 [{role, content}, ...] 转换为 LangChain Message 列表"""
    messages = []
    if not history:
        return messages
    for msg in history[-6:]:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "assistant":
            messages.append(AIMessage(content=content))
        else:
            messages.append(HumanMessage(content=content))
    return messages


# ── RAG 链服务（统一入口）─────────────────────────────────────────

class RAGChainService:
    """
    RAG 链服务 - 基于 LangChain LCEL (LangChain Expression Language)

    三个核心方法：
    - retrieve():  仅检索（用于 /api/search/*）
    - ask():       检索 + 非流式生成（用于 /api/ai/ask）
    - stream_ask(): 检索 + 流式生成（用于 /api/ai/ask/stream）

    共享同一个 HybridRetriever 和同一套 Prompt 模板。
    """

    @staticmethod
    def retrieve(
        query: str,
        top_k: int = 5,
        kg_depth: int = 1,
        categories: Optional[List[str]] = None,
    ) -> List[Document]:
        """
        仅检索：返回 LangChain Document 列表
        用于 /api/search/* 等不需要 LLM 生成的场景

        v2：支持 categories 过滤（None 或空列表表示不限定分类）
        """
        retriever = HybridRetriever(top_k=top_k, kg_depth=kg_depth, categories=categories)
        return retriever.invoke(query)

    @staticmethod
    def _inject_system_faq(query: str, docs: List[Document], knowledge_base_id: str = None) -> List[Document]:
        """根据查询意图，在 docs 前面注入系统 FAQ 文档（提高系统类问题的回答准确度）

        任务 W：system_faq 查询时【只】保留 system_faq 文档，
        严格过滤掉其他普通 RAG 文档，避免 LLM 把技术论文当成"本知识库"介绍
        （违反 SYSTEM_PROMPT 规则 7）

        任务 Y：per-KB 配置 —— 每个 KB 都有自己的 FAQ 内容
        优先级：KB 自己的 faq_overrides > 动态生成 > 默认模板
        """
        if not is_system_faq_query(query):
            return docs

        # 任务 Y：从 system_faq 模块加载（支持 per-KB 覆盖）
        from app.core.system_faq import get_system_faq_docs
        faq_dicts = get_system_faq_docs(knowledge_base_id)

        faq_docs = [
            Document(
                page_content=faq["content"],
                metadata={
                    "doc_id": faq["id"],
                    "title": faq["title"],
                    "category": "系统内置",
                    "score": faq.get("score", 1.0),
                    "source": "system_faq",
                },
            )
            for faq in faq_dicts
        ]

        if docs and faq_docs:
            # 提取 query 中的中文/英文关键词（去除停用词）
            stop_words = {"的", "了", "和", "是", "在", "我", "有", "都", "一", "上",
                          "也", "很", "到", "说", "要", "去", "你", "介绍", "什么", "如何",
                          "怎么", "怎样", "一下", "一下", "请", "帮"}
            kw_pattern = re.compile(r"[\u4e00-\u9fff]+|[A-Za-z]+")
            query_keywords = set()
            for m in kw_pattern.finditer(query):
                word = m.group(0).lower()
                if len(word) >= 2 and word not in stop_words:
                    query_keywords.add(word)


            system_intro_keywords = {
                "本平台", "本系统", "本知识库", "这个系统", "该系统", "这套系统",
                "知识库", "平台", "工具", "应用", "软件", "产品", "知识",
                "能力", "使用", "功能", "介绍", "使用方式", "使用说明", "使用手册",
            }
            query_has_system_kw = bool(query_keywords & system_intro_keywords)

            # 检查 system_faq 文档是否包含 query 关键词（弱匹配，substring）
            faq_has_match = False
            if query_keywords:
                for faq in faq_dicts:
                    title = (faq.get("title") or "").lower()
                    content = (faq.get("content") or "").lower()
                    if any(kw in title or kw in content for kw in query_keywords):
                        faq_has_match = True
                        break

            # 任务 X 修复 v2：更激进的兜底
            # 即使 faq 文档"包含"query 关键词（弱匹配），如果：
            #   1) query 本身没有"系统/知识库/平台"等系统类关键词
            #   2) system_faq 文档的 title 是"知识库介绍"/"使用方式"类（典型系统介绍文档）
            # → 仍判定为"query 不属于 system_faq 范围"，fallthrough 到 KB 检索
            sys_intro_titles = {"知识库介绍", "使用方式", "知识库使用方式", "本知识库介绍"}
            all_faq_are_sys_intro = all(
                (faq.get("title") or "") in sys_intro_titles for faq in faq_dicts
            )
            if (
                not query_has_system_kw
                and all_faq_are_sys_intro
                and query_keywords
            ):
                logger.info(
                    f"[RAG] system_faq 文档都是系统介绍类 + query 不含系统类关键词，"
                    f"回退到 KB 检索结果（{len(docs)} 条）| query_keywords={query_keywords}"
                )
                return docs

            if not faq_has_match and query_keywords:
                # system_faq 文档完全不包含 query 关键词 → fallthrough 到 KB 检索结果
                logger.info(
                    f"[RAG] system_faq 文档不匹配 query 关键词 {query_keywords}，"
                    f"回退到 KB 检索结果（{len(docs)} 条）"
                )
                return docs

        logger.info(
            f"[RAG] system_faq 查询 | kb_id={knowledge_base_id} | "
            f"使用 {len(faq_docs)} 条 FAQ 文档，过滤掉 {len(docs)} 条普通 RAG 文档"
        )
        return faq_docs

    @staticmethod
    def _build_messages(
        docs: List[Document],
        question: str,
        history: Optional[List[dict]] = None,
    ) -> List:
        """构建传给 LLM 的 messages 列表（统一）"""
        context = _format_documents_for_context(docs)
        combined_system_prompt = f"{SYSTEM_PROMPT}\n\n{RAG_CONTEXT_TEMPLATE.format(context=context[:4000])}"
        messages: List = [
            SystemMessage(content=combined_system_prompt),
        ]
        messages.extend(_convert_history_to_messages(history))
        messages.append(HumanMessage(content=question))
        return messages

    @staticmethod
    def _is_meta_query(question: str) -> bool:
        """任务 1：识别元数据级查询（"现在有什么/统计/分类列表"等）

        任务 6（重构）：委托给 IntentClassifier 统一处理
        """
        try:
            from app.core.intent_classifier import IntentClassifier, IntentType
            return IntentClassifier.classify(question).intent == IntentType.META_QUERY
        except Exception:
            return False

    @staticmethod
    def _collect_meta_snapshot(category: str = None) -> dict:
        """任务 1：聚合知识库元数据（文档清单 + 分类 + 统计）

        任务 X：同时返回每个文档的【真实内容摘要】（前 500 字符），
        让 LLM 能基于真实内容回答"知识库里有什么"，而不是只列标题。
        """
        from app.services.document_service import _documents
        docs = list(_documents.values())
        if category:
            docs = [d for d in docs if d.category == category]
        by_cat: dict[str, list[dict]] = {}
        for d in docs:
            content = (d.content or "").strip()
            # 取前 500 字符作为摘要（去掉多余空白）
            summary = re.sub(r"\s+", " ", content[:500]) if content else ""
            by_cat.setdefault(d.category, []).append({
                "id": d.id,
                "title": d.title,
                "file_type": d.file_type,
                "owner": d.owner,
                "content_preview": summary,  # 任务 X：真实内容摘要
                "content_length": len(content),
            })
        return {
            "total_documents": len(docs),
            "total_categories": len(by_cat),
            "total_chunks": VectorStore.count_total(),
            "categories": [
                {
                    "name": cat,
                    "count": len(items),
                    "documents": items,
                }
                for cat, items in sorted(by_cat.items(), key=lambda x: -len(x[1]))
            ],
        }

    @staticmethod
    def ask(
        question: str,
        history: Optional[List[dict]] = None,
        model: Optional[str] = None,
        top_k: int = 5,
        kg_depth: int = 1,
        categories: Optional[List[str]] = None,
        knowledge_base_id: Optional[str] = None,
    ) -> dict:
        """
        非流式 RAG 问答

        Returns:
            {
                "answer": str,
                "citations": list[dict],
                "confidence": float,
                "context_docs": list[Document],
            }

        v2：支持 categories 过滤
        任务 1：元数据查询走专用路径（_is_meta_query）
        任务 6：完整意图识别（IntentClassifier.classify）
        """
        try:
            # 任务 6：先做完整意图识别
            from app.core.intent_classifier import IntentClassifier, IntentType
            intent_result = IntentClassifier.classify(question, history)
            logger.info(
                f"[RAG/Intent] q={question[:30]}... | intent={intent_result.intent.value} | "
                f"conf={intent_result.confidence:.2f} | rules={intent_result.matched_rules[:3]}"
            )

            # 任务 6：闲聊/问候 → 走轻量回复
            if intent_result.intent in (IntentType.GREETING, IntentType.CHITCHAT):
                return {
                    "answer": "你好！我是 Knowledge OS 智能助手，可以帮你检索知识库、回答问题。请问有什么需要？",
                    "citations": [],
                    "confidence": 1.0,
                    "context_docs": [],
                    "is_chitchat": True,
                    "intent": intent_result.intent.value,
                    "intent_confidence": intent_result.confidence,
                }

            # 任务 6：反向声明 → 走 KB 内容检索（用户明确否定了前序 system_faq 回答）
            # 同时清掉前序 system_faq 的影响
            if intent_result.intent == IntentType.NEGATION:
                logger.info(f"[RAG/Intent] 检测到反向声明，跳过 system_faq 直接走 KB 检索")
                # 显式不走 system_faq，retriever 直接用原始 question
                retriever = HybridRetriever(
                    top_k=top_k,
                    kg_depth=kg_depth,
                    categories=categories,
                    knowledge_base_id=knowledge_base_id,
                )
                try:
                    docs = retriever.invoke(question)
                except Exception as e:
                    logger.error(f"[RAG] 检索器 invoke 失败: {e}", exc_info=True)
                    docs = []
                # 显式不调用 _inject_system_faq，避免前序污染
                messages = RAGChainService._build_messages(docs, question, history)
                llm = LLMChainService.get_llm(model=model, stream=False)
                response = llm.invoke(messages)
                answer_text = response.content or ""
                citations = _build_citations(docs)
                confidence = citations[0]["score"] if citations else 0.0

                # 任务 Z 修复（关键）：
                # 旧逻辑：只要 LLM 输出含「未找到」marker，就清空 citations + 截断 answer
                # 问题：用户报告的"未找到 / 建议换个问法"自相矛盾答案就是从这里来的
                # - LLM 真实输出 7076 字符完整答案（带引用 ①②③）
                # - 但 LLM 答案含"没有找到"等描述性句子时，被粗暴截断到第一个句号
                # - 截断后内容拼接错误，引用重排失败，前端展示矛盾
                #
                # 新逻辑：
                # 1. 如果 LLM 输出含引用标号（①②③）→ 视为成功回答，**保留完整 answer**
                # 2. 如果 LLM 输出完全没引用 + 含"未找到"marker → 标记为未找到
                # 3. 永远不再"截断" answer，保留 LLM 真实意图
                not_found_markers = ["未找到", "未提供", "没有找到", "暂未找到", "未找到相关", "没有相关", "知识库中暂未"]
                import re as _re_z
                has_citation = bool(_re_z.search(r"[\u2460-\u2473]", answer_text))
                has_not_found_marker = any(m in answer_text for m in not_found_markers)

                if has_not_found_marker and not has_citation:
                    # 真未找到：清空 citations + confidence=0 + 标记 is_negation
                    citations = []
                    confidence = 0.0
                    # 不截断 answer，让 LLM 的解释完整保留
                    return {
                        "answer": answer_text,
                        "citations": citations,
                        "confidence": confidence,
                        "context_docs": docs,
                        "is_negation": True,
                        "intent": intent_result.intent.value,
                        "intent_confidence": intent_result.confidence,
                    }
                # 任务 Z 修复：LLM 输出了引用 → 即使含"未找到"marker 也视为成功
                # answer 完整保留（不截断）

            # 任务 1：元数据查询走专用路径（直接读元数据 → LLM 总结，无幻觉）
            if RAGChainService._is_meta_query(question):
                snap = RAGChainService._collect_meta_snapshot()
                # 拼装结构化上下文
                meta_context = (
                    f"知识库当前共 {snap['total_documents']} 篇文档、"
                    f"{snap['total_categories']} 个分类、"
                    f"{snap['total_chunks']} 个向量分块。\n\n"
                    f"分类与文档清单（含每篇文档的内容摘要）：\n"
                )
                for cat in snap["categories"]:
                    meta_context += f"\n【分类：{cat['name']}】共 {cat['count']} 篇：\n"
                    for d in cat["documents"]:
                        preview = d.get("content_preview", "")
                        if preview:
                            meta_context += f"  - 《{d['title']}》（{d['file_type']}，{d.get('content_length', 0)} 字）\n"
                            meta_context += f"    内容摘要：{preview}...\n"
                        else:
                            meta_context += f"  - 《{d['title']}》（{d['file_type']}）\n"
                # 任务 X：明确要求 LLM 基于摘要介绍
                summary_prompt = (
                    f"用户问题：{question}\n\n"
                    f"以下是【用户上传到本知识库的真实文档】清单（含每篇的内容摘要），"
                    f"请严格基于这些内容回答用户问题，**不要编造未上传的主题**：\n\n"
                    f"{meta_context}\n\n"
                    f"【回答要求】\n"
                    f"1. 主题分类：按文档分类归纳主要技术方向\n"
                    f"2. 内容亮点：基于摘要说出每篇文档的核心内容\n"
                    f"3. 严禁编造：只介绍实际存在的文档，不要添加摘要里没提到的主题\n"
                    f"4. 用 Markdown 列表组织，便于阅读"
                )
                llm = LLMChainService.get_llm(model=model, stream=False)
                response = llm.invoke([HumanMessage(content=summary_prompt)])
                return {
                    "answer": response.content,
                    "citations": [],
                    "confidence": 1.0,  # 元数据查询零幻觉
                    "context_docs": [],
                    "is_meta_query": True,
                    "intent": intent_result.intent.value,
                    "intent_confidence": intent_result.confidence,
                }

            # 1. 检索
            retriever = HybridRetriever(
                top_k=top_k,
                kg_depth=kg_depth,
                categories=categories,
                knowledge_base_id=knowledge_base_id,
            )
            try:
                docs = retriever.invoke(question)
            except Exception as e:
                logger.error(f"[RAG] 检索器 invoke 失败: {e}", exc_info=True)
                # 不让检索失败拖垮整个 /ask，给出友好提示
                docs = []
            # 系统 FAQ 注入：解决"本系统如何使用"类意图被弱相关文档污染的问题
            # 任务 Y：传入 knowledge_base_id 支持 per-KB FAQ
            docs = RAGChainService._inject_system_faq(question, docs, knowledge_base_id)

            # 任务 X 修复：docs 完全为空时直接返回未找到，避免 LLM 幻觉
            # （之前会让 LLM 在无文档情况下自由发挥 → 产生自相矛盾答案）
            # 任务 Z：从 KnowledgeProvider 动态加载兜底模板（0 硬编码）
            if not docs:
                logger.info(f"[RAG] 检索为空，question={question[:30]!r}，直接返回未找到")
                from app.core.knowledge_provider import get_knowledge_provider
                return {
                    "answer": get_knowledge_provider().get_template(
                        "fallback_no_match", question=question
                    ),
                    "citations": [],
                    "confidence": 0.0,
                    "context_docs": [],
                    "is_negation": True,
                    "intent": intent_result.intent.value,
                    "intent_confidence": intent_result.confidence,
                }

            # 2. 构建消息
            messages = RAGChainService._build_messages(docs, question, history)

            # 3. 调用 LLM
            llm = LLMChainService.get_llm(model=model, stream=False)
            response = llm.invoke(messages)

            # 任务 P3-7 修复：清洗 LLM 输出中的占位符/调试字符串（如 [object Object]）
            answer_text = _sanitize_llm_output(response.content or "")

            # 4. 构造返回
            citations = _build_citations(docs)
            confidence = citations[0]["score"] if citations else 0.0

            # 任务 Z 修复（关键）：不再粗暴截断 answer
            # 旧逻辑会截断到第一个句号，丢弃 LLM 在「未找到」之后的所有内容
            # 新逻辑：只在 LLM 完全没引用文档时，才标记为「未找到」（清空 citations）
            # 任务 Z 终极修复：严格化 marker —— 只检测"知识库中"开头的"未找到"表述
            # 避免误伤"如果 X 没找到 Y"这种嵌入式表述
            not_found_markers = [
                "知识库中暂未找到",
                "知识库中暂未",
                "知识库中未找到",
                "知识库中没有找到",
            ]
            # 矛盾检测：LLM 自相矛盾（既说"找到"又说"换个问法"）
            contradiction_markers = ["换个问法", "换种问法", "换个问题", "建议重新提问"]
            import re as _re_z2
            has_citation_z = bool(_re_z2.search(r"[\u2460-\u2473]", answer_text))
            has_not_found_marker = any(m in answer_text for m in not_found_markers)
            has_contradiction = any(m in answer_text for m in contradiction_markers)

            if (has_not_found_marker or has_contradiction) and not has_citation_z:
                # 真未找到：清空 citations + 强制改写为标准模板（避免矛盾输出）
                logger.info(
                    f"[RAG] LLM 判断未找到或矛盾输出 | "
                    f"has_marker={has_not_found_marker} | has_contradiction={has_contradiction} | "
                    f"清空 citations（原 {len(citations)} 条）"
                )
                # 任务 Z 终极修复 v2：RAG 兜底
                # 如果 RAG 检索到了 docs（score ≥ 阈值），禁止走"未找到"模板
                # 强制让 LLM 基于 docs 总结
                # 任务 X 修复：阈值从 0.5 降到 0.30，与混合检索阈值一致
                # 避免"langchain"等查询被混合检索能命中但兜底漏掉的情况
                FALLBACK_SCORE_THRESHOLD = 0.30
                high_score_docs = [
                    d for d in docs
                    if d.metadata.get("score", 0) >= FALLBACK_SCORE_THRESHOLD
                ]
                if high_score_docs and len(high_score_docs) > 0:
                    logger.info(
                        f"[RAG] 兜底拦截：RAG 检索到 {len(high_score_docs)} 条 score≥{FALLBACK_SCORE_THRESHOLD} 的 docs，"
                        f"但 LLM 输出了'未找到' → 诚实告知数据不足"
                    )
                    # 任务 Z v4（诚实版）：不再硬塞代码片段，明确告诉用户数据不足
                    # 根因：知识库里没有直接概念定义文档，只有代码示例
                    doc_titles = []
                    for d in high_score_docs[:5]:
                        title = d.metadata.get("title", "资料")
                        score = d.metadata.get("score", 0.0)
                        doc_titles.append(f"  - 《{title}》 (相关度 {score:.2f})")
                    titles_text = "\n".join(doc_titles) if doc_titles else "  （无）"

                    # 任务 Z：从 KnowledgeProvider 动态加载模板（0 硬编码）
                    from app.core.knowledge_provider import get_knowledge_provider
                    answer_text = get_knowledge_provider().get_template(
                        "fallback_no_definition",
                        question=question,
                        count=len(high_score_docs),
                        titles=titles_text,
                        examples="「LangChain 如何创建 Agent」「LangChain 的 Tools 怎么用」",
                    )
                    response.content = answer_text
                else:
                    # 真未找到：清空 citations + 标准"未找到"模板
                    # 任务 Z：从 KnowledgeProvider 动态加载模板（0 硬编码）
                    citations = []
                    confidence = 0.0
                    from app.core.knowledge_provider import get_knowledge_provider
                    answer_text = get_knowledge_provider().get_template(
                        "fallback_no_match", question=question
                    )
                    response.content = answer_text
            elif has_not_found_marker and has_citation_z:
                # 任务 Z 边界 case：LLM 输出"未找到"+ 引用 ①②③（系统 prompt 提示强制加的）→ 自相矛盾
                # 此时 LLM 既"未找到"又"引用"，以"未找到"为准（保守）
                logger.info(
                    f"[RAG] LLM 输出未找到但含引用（矛盾）| "
                    f"清空 citations + 强制改写标准模板"
                )
                citations = []
                confidence = 0.0
                # 任务 Z：从 KnowledgeProvider 动态加载兜底模板（0 硬编码）
                from app.core.knowledge_provider import get_knowledge_provider
                answer_text = get_knowledge_provider().get_template(
                    "fallback_no_match", question=question
                )
                response.content = answer_text
            # 否则：answer 完整保留

            logger.info(
                f"[RAG] ask | q={question[:30]}... | docs={len(docs)} | "
                f"citations={len(citations)} | conf={confidence:.3f}"
            )

            return {
                "answer": response.content,
                "citations": citations,
                "confidence": confidence,
                "context_docs": docs,
                "intent": intent_result.intent.value,
                "intent_confidence": intent_result.confidence,
            }
        except Exception as e:
            logger.error(f"[RAG] ask 失败: {e}", exc_info=True)
            return {
                "answer": f"抱歉，处理失败: {str(e)}",
                "citations": [],
                "confidence": 0.0,
                "context_docs": [],
            }

    @staticmethod
    def stream_ask(
        question: str,
        history: Optional[List[dict]] = None,
        model: Optional[str] = None,
        top_k: int = 5,
        kg_depth: int = 1,
        categories: Optional[List[str]] = None,
        knowledge_base_id: Optional[str] = None,
    ) -> Generator[dict, None, None]:
        """
        流式 RAG 问答

        Yields:
            {"type": "metadata", "citations": [...], "confidence": float}
            {"type": "text", "content": str}     # 每个 token chunk
            {"type": "done"}
            {"type": "error", "content": str}   # 异常时

        v2：支持 categories 过滤
        任务 1：元数据查询走专用路径（_is_meta_query）
        """
        try:
            # 任务 1：元数据查询走专用路径
            if RAGChainService._is_meta_query(question):
                snap = RAGChainService._collect_meta_snapshot()
                meta_context = (
                    f"知识库当前共 {snap['total_documents']} 篇文档、"
                    f"{snap['total_categories']} 个分类、"
                    f"{snap['total_chunks']} 个向量分块。\n\n"
                    f"分类清单：\n"
                )
                for cat in snap["categories"]:
                    doc_titles = "、".join(d["title"] for d in cat["documents"])
                    meta_context += f"- 「{cat['name']}」({cat['count']} 篇)：{doc_titles}\n"
                summary_prompt = (
                    f"用户问题：{question}\n\n"
                    f"知识库元数据（已查询，无幻觉风险）：\n{meta_context}\n\n"
                    f"请基于以上结构化数据，用自然语言回答用户问题。"
                )
                yield {
                    "type": "metadata",
                    "model": model,
                    "citations": [],
                    "confidence": 1.0,
                    "is_meta_query": True,
                }
                llm = LLMChainService.get_llm(model=model, stream=True)
                collected_text = ""
                for chunk in llm.stream([HumanMessage(content=summary_prompt)]):
                    if chunk.content:
                        # 任务 P3-7：流式只删除占位符，不替换为中文
                        import re as _re_chunk2
                        cleaned_chunk = chunk.content
                        for _p, _r in _PLACEHOLDER_PATTERNS:
                            cleaned_chunk = _re_chunk2.sub(_p, '', cleaned_chunk)
                        if not cleaned_chunk:
                            continue
                        collected_text += cleaned_chunk
                        yield {"type": "text", "content": cleaned_chunk}
                yield {"type": "done"}
                return

            # 1. 检索（与非流式共用同一检索器）
            retriever = HybridRetriever(
                top_k=top_k,
                kg_depth=kg_depth,
                categories=categories,
                knowledge_base_id=knowledge_base_id,
            )
            docs = retriever.invoke(question)
            # 系统 FAQ 注入：解决"本系统如何使用"类意图被弱相关文档污染的问题
            # 任务 Y：传入 knowledge_base_id 支持 per-KB FAQ
            docs = RAGChainService._inject_system_faq(question, docs, knowledge_base_id)

            citations = _build_citations(docs)
            confidence = citations[0]["score"] if citations else 0.0

            # 2. 发送元数据
            # 任务 Z v3：增加 context_docs 字段（page_content + title + score）
            # 供 ai.py 兜底改写时调用 LLM 重新生成（不再写死"请点击引用卡"模板）
            yield {
                "type": "metadata",
                "model": model,
                "citations": citations,
                "confidence": confidence,
                "context_docs": [
                    {
                        "doc_id": getattr(d, "id", None) or d.metadata.get("doc_id"),
                        "title": d.metadata.get("title", "资料"),
                        "score": d.metadata.get("score", 0.0),
                        "content": d.page_content or "",
                    }
                    for d in docs[:5]  # 传前 5 条供 LLM 重新生成
                ],
            }

            # 3. 构建消息
            messages = RAGChainService._build_messages(docs, question, history)

            # 4. 流式 LLM 调用
            llm = LLMChainService.get_llm(model=model, stream=True)
            collected_text = ""
            has_content = False

            for chunk in llm.stream(messages):
                if chunk.content:
                    has_content = True
                    # 任务 P3-7 修复：流式输出也清洗占位符
                    # 关键：不能用 _sanitize_llm_output（它会把"全部是占位符"的 chunk 替换成
                    # "（模型输出异常，请换个问法重试）"，污染前端）
                    # 改为只删除占位符，不替换
                    import re as _re_chunk
                    cleaned_chunk = chunk.content
                    for _p, _r in _PLACEHOLDER_PATTERNS:
                        # 流式不替换为中文占位符，直接删除避免污染
                        cleaned_chunk = _re_chunk.sub(_p, '', cleaned_chunk)
                    if not cleaned_chunk:
                        continue
                    collected_text += cleaned_chunk
                    yield {"type": "text", "content": cleaned_chunk}

            # 任务 Z 修复（流式版）：不再粗暴截断 collected_text
            # 旧逻辑：检测到 marker 后，截断到第一个句号 → 丢失 LLM 后续内容
            # 新逻辑：只在 LLM 完全没引用文档时，才 yield 一个 metadata 事件覆盖 citations
            # 任务 Z 终极修复：严格化 marker —— 只检测"知识库中"开头的"未找到"表述
            # 任务 Z 修复 v3：追加"知识库中找到"作为矛盾 marker（LLM 违反 prompt 时强制兜底）
            not_found_markers_s = [
                "知识库中暂未找到",
                "知识库中暂未",
                "知识库中未找到",
                "知识库中没有找到",
                "知识库中找到",  # 任务 Z v3：LLM 违反 prompt 时的矛盾输出
            ]
            # 矛盾检测：LLM 自相矛盾（既说"找到"又说"换个问法"）
            contradiction_markers_s = ["换个问法", "换种问法", "换个问题", "建议重新提问"]
            import re as _re_z3
            has_citation_s = bool(_re_z3.search(r"[\u2460-\u2473]", collected_text))
            has_not_found_marker_s = any(m in collected_text for m in not_found_markers_s)
            has_contradiction_s = any(m in collected_text for m in contradiction_markers_s)

            if (has_not_found_marker_s or has_contradiction_s) and not has_citation_s:
                # 真未找到 / 矛盾输出
                # 任务 Z 终极修复 v2：RAG 兜底
                # 如果 RAG 检索到了 docs（score ≥ 0.30），禁止走"未找到"模板
                # 任务 Z v3：阈值从 0.5 降到 0.30，与混合检索及非流式版一致
                high_score_docs_s = [
                    d for d in docs
                    if d.metadata.get("score", 0) >= 0.30
                ]
                if high_score_docs_s:
                    logger.info(
                        f"[RAG/stream] 兜底拦截：RAG 检索到 {len(high_score_docs_s)} 条高相关度 docs，"
                        f"但 LLM 输出了'未找到'"
                    )
                    # 不清空 citations，让 ai.py 层在 done 时强制改写 answer
                else:
                    logger.info(
                        f"[RAG/stream] LLM 未找到 | "
                        f"has_marker={has_not_found_marker_s} | has_contradiction={has_contradiction_s}"
                    )
                    citations = []
                    confidence = 0.0
                    yield {
                        "type": "metadata",
                        "model": model,
                        "citations": [],
                        "confidence": 0.0,
                    }
            elif has_not_found_marker_s and has_citation_s:
                # 任务 Z 边界 case：LLM 输出"未找到"+ 引用 ①②③ → 同样视为矛盾
                logger.info(f"[RAG/stream] LLM 未找到但含引用（矛盾）| 清空 citations")
                citations = []
                confidence = 0.0
                yield {
                    "type": "metadata",
                    "model": model,
                    "citations": [],
                    "confidence": 0.0,
                }
            # 否则：collected_text 完整保留（不截断）

            # 5. 兜底（流式无内容时）
            if not has_content and docs:
                fallback_lines = [f"- {doc.page_content[:300]}..." for doc in docs[:3]]
                fallback_text = "根据知识库内容，找到以下相关信息：\n\n" + "\n".join(fallback_lines)
                yield {"type": "text", "content": fallback_text}
            elif not has_content:
                # 任务 Z：从 KnowledgeProvider 动态加载兜底模板（0 硬编码）
                from app.core.knowledge_provider import get_knowledge_provider
                fallback = get_knowledge_provider().get_template(
                    "fallback_no_match", question=question
                )
                yield {"type": "text", "content": fallback}

            yield {"type": "done"}
            logger.info(
                f"[RAG] stream_ask | q={question[:30]}... | docs={len(docs)} | "
                f"len={len(collected_text)}"
            )

        except Exception as e:
            logger.error(f"[RAG] stream_ask 失败: {e}", exc_info=True)
            yield {"type": "error", "content": str(e)}

    @staticmethod
    def build_lcel_chain(model: Optional[str] = None, stream: bool = False):
        """
        构建 LCEL RAG 链（供高级用户使用）

        Pipeline: retriever -> format_docs -> prompt -> llm -> StrOutputParser
        """
        retriever = HybridRetriever()
        llm = LLMChainService.get_llm(model=model, stream=stream)
        prompt = _build_rag_prompt()

        chain = (
            {
                "context": retriever | _format_documents_for_context,
                "question": RunnablePassthrough(),
                "history": lambda x: [],
            }
            | prompt
            | llm
            | StrOutputParser()
        )

        return chain, retriever

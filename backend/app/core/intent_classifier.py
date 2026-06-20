"""
用户意图识别模块

设计目标：
- 全场景覆盖（问候/闲聊/元数据/系统FAQ/知识库内容/追问/越界等）
- 抗噪（emoji/纯表情/超长文本/纯符号/空字符串）
- 可配置（规则与同义词分离到 config 数据）
- 可测试（独立 service，不耦合 RAG 业务）
- 决策可观测（每条 query 输出 matched_patterns 与 confidence）

核心架构：
- IntentType 枚举：定义所有支持的意图
- IntentRule 数据类：单条匹配规则（keywords/patterns/weight）
- IntentConfig 配置：按 IntentType 聚合规则
- IntentClassifier 服务：主入口，混合策略匹配

匹配策略（按优先级递减）：
1. 显式否定（"不要 / 不是 / 拒绝"前缀）→ 反向意图
2. 问候/闲聊模板（白名单）→ 短回复类
3. 元数据查询关键词（"多少/统计/列出"）→ META_QUERY
4. 系统FAQ 关键词（"本系统/介绍/你是什么"）→ SYSTEM_FAQ
5. 知识库内容查询（默认）→ KB_CONTENT_QUERY
6. 追问特征（指代词+追问关键词+短句）→ FOLLOWUP
7. 越界（与业务无关的纯通用知识）→ OUT_OF_SCOPE

匹配算法：
- 关键词匹配：归一化（lowercase/去标点）后 substring 包含
- 正则匹配：re.search
- 权重累加：每个匹配的 keyword/pattern 增加权重，超过阈值才认定
- 优先级冲突：按上面的"匹配策略"顺序短路

容错：
- 空字符串/纯空白 → CHITCHAT
- 纯 emoji/纯标点 → CHITCHAT
- 超长文本（> 2000 字符）→ 截断处理
- 编码异常 → 退化为 UTF-8 替换

可观测性：
- classify() 返回 IntentResult（含 type / confidence / matched_rules / reason）
- 业务层可基于 matched_rules 做更细粒度路由
"""
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Set

logger = logging.getLogger(__name__)


# ============== 1. 意图枚举 ==============
class IntentType(str, Enum):
    """意图类型枚举

    业务路由映射：
    - GREETING / CHITCHAT / OUT_OF_SCOPE：轻量回复模板（不走 RAG）
    - META_QUERY：走元数据快照（直接读 documents.json）
    - SYSTEM_FAQ：注入 system_faq 文档
    - KB_CONTENT_QUERY：走 RAG 检索
    - FOLLOWUP：走 RAG + 主题扩展
    - NEGATION：反向声明（"我不要 X"），需特殊提示语
    - UNKNOWN：兜底（按 KB_CONTENT_QUERY 处理，但打告警）
    """
    GREETING = "greeting"           # 问候/寒暄
    CHITCHAT = "chitchat"           # 闲聊/无意义输入
    META_QUERY = "meta_query"       # 元数据查询
    SYSTEM_FAQ = "system_faq"       # 系统能力介绍
    KB_CONTENT_QUERY = "kb_content" # 知识库内容查询
    FOLLOWUP = "followup"           # 追问
    NEGATION = "negation"           # 反向声明
    OUT_OF_SCOPE = "out_of_scope"   # 越界
    UNKNOWN = "unknown"             # 兜底


# ============== 2. 数据类 ==============
@dataclass
class IntentRule:
    """单条意图规则"""
    keywords: List[str] = field(default_factory=list)     # 子串包含关键词
    patterns: List[str] = field(default_factory=list)     # 正则表达式
    weight: float = 1.0                                   # 命中权重
    description: str = ""                                 # 规则说明（可观测）


@dataclass
class IntentResult:
    """意图识别结果"""
    intent: IntentType                                    # 主意图
    confidence: float                                     # 置信度 0-1
    matched_rules: List[str] = field(default_factory=list)  # 命中的规则（可观测）
    reason: str = ""                                      # 决策理由（可观测）
    # 调试信息
    query_normalized: str = ""                            # 归一化后的 query
    query_length: int = 0                                 # 原始 query 长度


# ============== 3. 归一化工具 ==============
def _normalize_text(text: str) -> str:
    """归一化文本：去前后空白、转小写、合并连续空白"""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip().lower())


def _is_pure_emoji_or_punct(text: str) -> bool:
    """检测是否纯 emoji/标点/空白（无有效语义）"""
    if not text or not text.strip():
        return True
    # 保留：中日韩文字、英文字母、数字（CJK + ASCII）
    meaningful_chars = re.findall(
        "["
        + "\u4e00-\u9fff"   # CJK Unified Ideographs
        + "\u3040-\u30ff"   # Hiragana/Katakana
        + "\u3400-\u4dbf"   # CJK Extension A
        + "\uf900-\ufaff"   # CJK Compatibility Ideographs
        + "\uff00-\uffef"   # Halfwidth/Fullwidth
        + "a-zA-Z0-9"       # ASCII
        + "]",
        text,
        flags=re.UNICODE,
    )
    return len(meaningful_chars) == 0


def _is_pure_punctuation_only(text: str) -> bool:
    """检测是否纯标点（包含中英文全/半角标点，但不含任何文字/数字/emoji）"""
    if not text or not text.strip():
        return True
    # 把所有"非标点"剔除后看是否还有内容
    non_punct = re.findall(
        r"[^\s\W_]",
        text,
        flags=re.UNICODE,
    )  # 字母数字 = 标点符号之外
    return len(non_punct) == 0


def _count_emoji(text: str) -> int:
    """粗略统计 emoji 数量（用于容错）"""
    emoji_pattern = re.compile(
        r"[\U0001F600-\U0001F64F"
        r"\U0001F300-\U0001F5FF"
        r"\U0001F680-\U0001F6FF"
        r"\U0001F1E0-\U0001F1FF"
        r"\U00002702-\U000027B0"
        r"\U000024C2-\U0001F251"
        r"]+",
        flags=re.UNICODE,
    )
    return len(emoji_pattern.findall(text))


# ============== 4. 配置数据 ==============
class IntentConfig:
    """意图规则配置

    所有规则集中在此处，方便审计、调整、扩展。
    新增意图：在此添加对应的类属性。
    """

    # ---------- 4.1 问候/闲聊 ----------
    GREETING_RULES = IntentRule(
        keywords=[
            "你好", "您好", "hi", "hello", "hey", "嗨", "哈喽",
            "早上好", "中午好", "下午好", "晚上好", "早安", "晚安",
            "在吗", "在么", "在不在", "在么？",
        ],
        patterns=[
            r"^你好[呀啊哇呢]*[!！.。?？\s]*$",
            r"^(hi|hello|hey)[!！.。?？\s]*$",
            r"^在[吗么呢]*[?？!！.。\s]*$",
        ],
        weight=1.0,
        description="问候/寒暄",
    )

    CHITCHAT_RULES = IntentRule(
        keywords=[
            "哈哈", "呵呵", "嘻嘻", "嘿嘿", "嗯嗯", "好的", "收到",
            "再见", "拜拜", "bye", "ok",
        ],
        patterns=[
            r"^[哈哈呵呵嘻嘻嘿嘿嗯哦唔]{2,}$",  # 纯语气词
            r"^(好的|收到|ok|OK|好的好的)$",
            r"^(再见|拜拜|bye)[!！.。\s]*$",
        ],
        weight=0.8,
        description="闲聊/语气词",
    )

    # ---------- 4.2 元数据查询 ----------
    META_QUERY_RULES = IntentRule(
        keywords=[
            "多少篇", "多少个", "统计", "分类列表", "分类", "哪些文档",
            "列出", "清单", "几个文档", "总共有", "一共有", "共多少",
        ],
        patterns=[
            r"(多少|几)(篇|个|条|份)?(文档|资料|文件|分类)",
            r"(列出|展示|看看).*?(文档|分类|列表|清单)",
            r"^(知识库里|库中|库里).{0,10}(有|包含)",
            # 任务 6 修复：单独的"有哪些"应不包含"哪些组件"——后者是 KB 内容查询
            r"^.{0,5}有(哪|什么)些\s*(文档|资料|文件|分类|内容)",
        ],
        weight=1.2,
        description="元数据查询：知识库统计/清单",
    )

    # ---------- 4.3 系统 FAQ ----------
    SYSTEM_FAQ_RULES = IntentRule(
        keywords=[
            "本系统", "这个系统", "该系统", "系统如何", "如何用", "怎么用",
            "如何使用", "使用教程", "使用指南", "使用说明", "使用手册",
            "使用帮助", "功能介绍", "使用介绍", "系统介绍", "功能说明",
            "操作指南", "操作手册", "操作说明", "操作教程",
            "能做什么", "有什么功能", "可以做什么", "能做啥",
            "你是谁", "你是什么", "你能做什么", "你会什么",
        ],
        patterns=[
            r"^(介绍|了解|认识).*?(知识库|系统|平台|工具|你|您)",
            r"^(什么是|啥是|啥叫)",
            r"^你(是什么|是谁|能做什么|有什么功能|叫什么)",
            r"^(系统|平台|工具|知识库).*?(能做|可以|功能|能力)",
            r"^(帮助|help|使用教程|使用指南)$",
            r"^(怎么|如何)(用|使用|操作|上手)",
            r"(本系统|本平台|这个系统|该系统|这套系统)",
            r"^(这个|该|本).*?(知识库|系统|平台|工具).*?(介绍|是什么|功能|能力)",
            r"(知识库|系统|平台|工具).*?(介绍|说明|简介|概览)",
            # 任务 X 修复：严格化"介绍一下"——必须后接【系统/平台/知识库/工具】才算 system_faq
            # 防止"介绍一下 LangChain/RAG/Agent"等具体技术名词被误判为系统介绍
            # 修复 v2：必须接 系统/知识库 等具体词（去掉可选），否则放过 → 走 KB_CONTENT_QUERY
            r"^介绍一下\s*(本|这个|该|当前|我的)?\s*(知识库|系统|平台|工具|应用|软件|产品)\s*[?？。!！]?$",
        ],
        weight=1.0,
        description="系统能力/使用介绍",
    )

    # ---------- 4.4 反向声明（关键修复点） ----------
    NEGATION_RULES = IntentRule(
        keywords=[
            # 任务 6 修复：移除过于宽泛的单字（"别" 会误伤"区别"），改为短语
            "不是要", "不是问", "不是该", "不要", "拒绝", "算了",
            "我让你", "我让你介绍", "我要的是", "我要的不是", "我说的是",
            "不是说", "我要看的是", "我关心的是", "我说的是",
            "说的是", "想问的是", "想问的", "请回答", "看清楚",
            "你没听懂", "没听懂", "听不懂", "懂了吗", "懂了吗？",
            "看清楚问题", "看清楚了吗",
        ],
        patterns=[
            r"^(我|请|麻烦|要|要你).*?(不要|不是|拒绝)",
            r"^(我|请).*?(说|问|介绍|关心|要|想)",
            r"(我|要|请).{0,20}(说|问|想|关心|要)的(是|就是)",
            r"(看清楚|看仔细|听清楚|听懂).{0,10}(问题|问的|要)",
            # 关键修复：用户对前序回答不满意的强烈信号
            r"^(我|请).{0,10}(让你|要你|希望你).*?(介绍|回答|说|讲)",
            r"^(我让你|我要|我想).*?(介绍|回答|讲|说说)",
            r"(我|要).{0,5}(让你|要你).{0,15}(介绍|回答|说).{0,15}(而|不|别)",
            r"(不是|而非|不|没|未).{0,5}(该|本|这个).{0,5}(系统|平台|工具)",
            r"你没.{0,5}(听懂|理解|明白|搞清楚)",
            r"(没|没有).{0,5}(听懂|理解|明白)",
        ],
        weight=1.5,
        description="反向声明/纠正类（前序回答不正确）",
    )

    # ---------- 4.5 越界（与知识库无关的纯通用知识） ----------
    OUT_OF_SCOPE_RULES = IntentRule(
        keywords=[
            "天气预报", "今天星期几", "现在是几点", "几点了",
            "汇率", "股票", "比特币",
        ],
        patterns=[
            r"^(今天|明天|昨天|今晚|明早).{0,8}(天气|星期|几点|日期|会.*?雨|晴|阴|雪)",
            r"^(现在|今天|明天).{0,8}(几[点号]|什么时间)",
            r"(会|能).{0,3}(下雨|下雪|晴天|阴天)",
            r"^(什么|多少)(时候|时间)",
            r"^(汇率|股票|比特币|黄金|油价)",
            r"(穿着|穿什么|该穿)",
        ],
        weight=0.9,
        description="完全脱离业务范围",
    )

    # ---------- 4.6 追问特征（仅当 is_followup 判定为真时使用） ----------
    FOLLOWUP_INDICATORS = IntentRule(
        keywords=[],  # 追问主要靠 PRONOUN + FOLLOWUP_PATTERNS，配置在 FollowUpDetector
        patterns=[],
        weight=0.0,
        description="追问特征（实际逻辑在 FollowUpDetector 中）",
    )


# ============== 5. 分类器主体 ==============
class IntentClassifier:
    """用户意图分类器

    使用方法：
        result = IntentClassifier.classify("介绍一下知识库")
        if result.intent == IntentType.SYSTEM_FAQ:
            ...
    """

    # 噪音输入特征：仅 emoji、仅标点、超短无意义
    NOISE_INPUT_MAX_LENGTH = 2  # 长度 <= 2 字符且无中文/英文/数字

    # 极长文本阈值：超过该长度截断处理（防止 prompt 注入）
    MAX_QUERY_LENGTH = 2000

    @classmethod
    def classify(
        cls,
        query: str,
        history: Optional[List[dict]] = None,
    ) -> IntentResult:
        """主入口：分类用户意图

        Args:
            query: 原始用户输入
            history: 对话历史 [{role, content}, ...]

        Returns:
            IntentResult: 意图识别结果
        """
        history = history or []
        original_query = query or ""
        query_length = len(original_query)

        # === Step 0：异常输入容错 ===
        if not original_query or not original_query.strip():
            return IntentResult(
                intent=IntentType.CHITCHAT,
                confidence=0.99,
                matched_rules=["noise:empty"],
                reason="输入为空",
                query_normalized="",
                query_length=0,
            )

        normalized = _normalize_text(original_query)

        # 仅 emoji / 仅标点
        if _is_pure_emoji_or_punct(original_query) or _is_pure_punctuation_only(original_query):
            return IntentResult(
                intent=IntentType.CHITCHAT,
                confidence=0.95,
                matched_rules=["noise:pure_emoji_or_punct"],
                reason="纯表情/标点输入",
                query_normalized=normalized,
                query_length=query_length,
            )

        # 极长输入截断
        if query_length > cls.MAX_QUERY_LENGTH:
            logger.warning(
                f"[Intent] 输入过长 ({query_length} > {cls.MAX_QUERY_LENGTH})，已截断"
            )
            original_query = original_query[: cls.MAX_QUERY_LENGTH]
            normalized = _normalize_text(original_query)

        # === Step 1：反向声明检测（关键：优先级最高） ===
        neg_score, neg_rules = cls._match_rule(normalized, IntentConfig.NEGATION_RULES)
        if neg_score > 0:
            return IntentResult(
                intent=IntentType.NEGATION,
                confidence=min(0.95, 0.6 + neg_score * 0.1),
                matched_rules=neg_rules,
                reason="检测到反向声明/纠正类表达",
                query_normalized=normalized,
                query_length=query_length,
            )

        # === Step 2：问候/闲聊检测 ===
        greet_score, greet_rules = cls._match_rule(normalized, IntentConfig.GREETING_RULES)
        chit_score, chit_rules = cls._match_rule(normalized, IntentConfig.CHITCHAT_RULES)
        if greet_score > 0 and greet_score >= chit_score:
            return IntentResult(
                intent=IntentType.GREETING,
                confidence=min(0.95, 0.5 + greet_score * 0.15),
                matched_rules=greet_rules,
                reason="检测到问候语",
                query_normalized=normalized,
                query_length=query_length,
            )
        if chit_score > 0:
            return IntentResult(
                intent=IntentType.CHITCHAT,
                confidence=min(0.9, 0.4 + chit_score * 0.15),
                matched_rules=chit_rules,
                reason="检测到闲聊/语气词",
                query_normalized=normalized,
                query_length=query_length,
            )

        # === Step 3：追问检测（优先级比 system_faq / meta_query 高）
        # 任务 6 修复：含"这些/那些/这个/那个"等指代词的问句应优先识别为追问
        # 而不是 system_faq（"这些怎么用" 不应被判为 system_faq）
        if history:
            try:
                from app.core.memory_chain import FollowUpDetector
                if FollowUpDetector.is_follow_up(original_query, history):
                    return IntentResult(
                        intent=IntentType.FOLLOWUP,
                        confidence=0.75,
                        matched_rules=["followup:detector"],
                        reason="检测到追问特征（指代词/追问关键词）",
                        query_normalized=normalized,
                        query_length=query_length,
                    )
            except Exception as e:
                logger.warning(f"[Intent] 追问检测失败: {e}")

        # === Step 4：元数据查询（与 system_faq 互斥） ===
        meta_score, meta_rules = cls._match_rule(normalized, IntentConfig.META_QUERY_RULES)
        faq_score, faq_rules = cls._match_rule(normalized, IntentConfig.SYSTEM_FAQ_RULES)

        # 任务 X：META_QUERY 高优先级 override patterns
        # 当用户问"介绍一下本知识库/我的知识库/我上传的知识/现有知识库"时，
        # 用户实际想看的是【自己上传的文档内容】，而不是 system 功能介绍
        # → 强制路由到 META_QUERY 路径（基于 _documents 真实内容回答）
        meta_override_patterns = [
            r"^(介绍|了解|认识|说说|看看).{0,5}(本|我的|这个|该|当前|现有)?(知识库|资料库|文档库|文档集|知识集)",
            r"^(本|我的|这个|该|当前|现有)?(知识库|资料库|文档库).{0,8}(介绍|有什么|有哪些|内容|知识|资料)",
            r"^(我)?(上传|收录|存储|导入)的?.*?(内容|文档|资料|知识)",
            r"^(我)?(的)?知识库里.{0,5}有",
            r"^(本|我的|现有|当前)?(知识库|资料库).{0,5}(有|包含).{0,5}(什么|哪些|啥)",
        ]
        for pat in meta_override_patterns:
            if re.search(pat, normalized):
                return IntentResult(
                    intent=IntentType.META_QUERY,
                    confidence=0.92,
                    matched_rules=[f"override:meta_priority:{pat[:25]}"] + (faq_rules[:1] or meta_rules[:1]),
                    reason="用户想了解『本知识库内有什么内容/知识』→ 走 META_QUERY 路径，基于用户文档内容回答",
                    query_normalized=normalized,
                    query_length=query_length,
                )

        # system_faq 优先于 meta_query
        if faq_score > 0:
            # 任务 6 修复：当 query 形如"什么是 X"且 X 是个具体技术名词时，
            # 实际是知识库内容查询（KB_CONTENT_QUERY），不是 system_faq
            kb_content_override_patterns = [
                r"^什么是\s*\S+",     # "什么是 X" 且 X 非空
                r"^.{0,8}的?(原理|核心|组件|模块|区别|对比|实现|工作流|架构)",
                r"^(介绍|解释|说说).{0,10}(核心|原理|组件|架构|实现)",
                # 任务 X 修复 v2：防御性兜底 —— 如果"介绍一下"后接具体技术词
                # （RAG/Agent/LangChain/Prompt 等），强制走 KB_CONTENT_QUERY
                r"^介绍一下\s+(RAG|Agent|LangChain|LLM|Prompt|Embedding|Transformer|GPT|Claude|DeepSeek|Qwen|知识图谱|大模型|提示词|向量|检索|知识库索引)\b",
                # 通用兜底：介绍一下 <非系统名词> 也走 KB
                r"^介绍一下\s+(?!本|这个|该|当前|我的|知识库|系统|平台|工具|应用|软件|产品)\S+",
            ]
            for pat in kb_content_override_patterns:
                if re.search(pat, normalized):
                    return IntentResult(
                        intent=IntentType.KB_CONTENT_QUERY,
                        confidence=0.65,
                        matched_rules=["override:kb_content_priority"] + faq_rules[:2],
                        reason=f"被 system_faq 误伤 → 实际是知识库内容查询",
                        query_normalized=normalized,
                        query_length=query_length,
                    )
            return IntentResult(
                intent=IntentType.SYSTEM_FAQ,
                confidence=min(0.95, 0.5 + faq_score * 0.1),
                matched_rules=faq_rules,
                reason="检测到系统能力/使用介绍类问题",
                query_normalized=normalized,
                query_length=query_length,
            )
        if meta_score > 0:
            return IntentResult(
                intent=IntentType.META_QUERY,
                confidence=min(0.95, 0.5 + meta_score * 0.1),
                matched_rules=meta_rules,
                reason="检测到元数据查询",
                query_normalized=normalized,
                query_length=query_length,
            )

        # === Step 5：越界检测 ===
        oos_score, oos_rules = cls._match_rule(normalized, IntentConfig.OUT_OF_SCOPE_RULES)
        if oos_score > 0:
            return IntentResult(
                intent=IntentType.OUT_OF_SCOPE,
                confidence=min(0.85, 0.4 + oos_score * 0.15),
                matched_rules=oos_rules,
                reason="问题完全脱离业务范围",
                query_normalized=normalized,
                query_length=query_length,
            )

        # === Step 6：默认：知识库内容查询 ===
        return IntentResult(
            intent=IntentType.KB_CONTENT_QUERY,
            confidence=0.5,
            matched_rules=["default:kb_content"],
            reason="默认路由：知识库内容检索",
            query_normalized=normalized,
            query_length=query_length,
        )

    @classmethod
    def _match_rule(cls, query: str, rule: IntentRule) -> tuple:
        """匹配单条规则，返回 (分数, 命中的子规则列表)"""
        score = 0.0
        matched = []

        # 关键词匹配（归一化后的 substring）
        for kw in rule.keywords:
            if kw.lower() in query:
                score += rule.weight
                matched.append(f"kw:{kw}")

        # 正则匹配
        for pat in rule.patterns:
            try:
                if re.search(pat, query):
                    score += rule.weight
                    matched.append(f"pat:{pat[:30]}")
            except re.error:
                continue

        return score, matched


# ============== 6. 便捷函数 ==============
def classify_query(query: str, history: Optional[List[dict]] = None) -> IntentResult:
    """便捷函数：分类用户意图（推荐使用）"""
    return IntentClassifier.classify(query, history)


# ============== 7. 兼容旧 API ==============
def is_system_faq_query(query: str) -> bool:
    """兼容旧 API：判断是否 system_faq"""
    return IntentClassifier.classify(query).intent == IntentType.SYSTEM_FAQ

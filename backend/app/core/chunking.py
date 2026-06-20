"""
分块策略模块 - 支持14种分块策略
与前端 DragUpload、SettingsPage 保持一致

支持的策略：
- auto: 智能推荐（由LLM分析推荐）
- recursive: 递归分块
- fixed: 固定大小
- structure: 基于结构
- semantic: 语义分块
- naive: 简单分块
- general: 通用分块
- intelligent: 智能分块
- parent_child: 父子分块
- book: 书籍分块
- paper: 论文分块
- resume: 简历分块
- qa: 问答对分块
- table: 表格分块
"""
import re
import json
import os
from typing import List, Dict, Optional
from dataclasses import dataclass

from app.core.llm import LLMService

# ── 分类持久化 ──────────────────────────────────────────────────

CATEGORIES_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'categories.json')

def _category_file_path():
    return os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'categories.json')

def _save_categories():
    """任务 P0-2: 优先 SQLite，fallback JSON"""
    try:
        from app.core.db import get_db_session
        from app.core.models import Category
        with get_db_session() as session:
            for name, cfg in ChunkingService.CATEGORY_CONFIGS.items():
                existing = session.query(Category).filter_by(id=name).first()
                if existing:
                    existing.strategy = cfg.strategy
                    existing.chunk_size = cfg.chunk_size
                    existing.overlap = cfg.overlap
                else:
                    session.add(Category(
                        id=name, strategy=cfg.strategy,
                        chunk_size=cfg.chunk_size, overlap=cfg.overlap
                    ))
        return  # 成功写入 SQLite
    except Exception as e:
        print(f"[警告] SQLite 分类持久化失败, fallback JSON: {e}")
    # Fallback: JSON
    try:
        os.makedirs(os.path.dirname(_category_file_path()), exist_ok=True)
        data = {}
        for name, cfg in ChunkingService.CATEGORY_CONFIGS.items():
            data[name] = {"strategy": cfg.strategy, "chunk_size": cfg.chunk_size, "overlap": cfg.overlap}
        with open(_category_file_path(), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[警告] 分类持久化失败: {e}")


def _load_categories():
    """任务 P0-2: 优先 SQLite，fallback JSON"""
    data = {}
    try:
        from app.core.db import get_db_session
        from app.core.models import Category
        with get_db_session() as session:
            rows = session.query(Category).all()
            for r in rows:
                data[r.id] = {
                    "strategy": r.strategy, "chunk_size": r.chunk_size, "overlap": r.overlap
                }
        if data:
            print(f"[INFO] 从 SQLite 加载了 {len(data)} 个分类配置")
    except Exception as e:
        print(f"[警告] SQLite 分类加载失败, fallback JSON: {e}")
        # Fallback: JSON
        try:
            fp = _category_file_path()
            if os.path.exists(fp):
                with open(fp, 'r', encoding='utf-8') as f:
                    data = json.load(f)
        except Exception as e2:
            print(f"[警告] 分类 JSON 加载也失败: {e2}")
    # 应用到 ChunkingService
    for name, cfg in data.items():
        if name not in ChunkingService.CATEGORY_CONFIGS:
            ChunkingService.CATEGORY_CONFIGS[name] = ChunkConfig(
                strategy=cfg.get("strategy", "recursive"),
                chunk_size=cfg.get("chunk_size", 500),
                overlap=cfg.get("overlap", 100),
            )


@dataclass
class ChunkConfig:
    """分块配置"""
    strategy: str = "recursive"
    # 任务：提升分块密度（500→400 字符，召回更细粒度信息）
    # 配合 overlap=80 保持语义连续性
    chunk_size: int = 400
    overlap: int = 80


class ChunkingService:
    """分块服务"""

    # 默认分类配置 - 可动态扩展
    CATEGORY_CONFIGS: Dict[str, ChunkConfig] = {
        "默认": ChunkConfig(strategy="recursive", chunk_size=500, overlap=100),
    }

    # 策略映射：将前端策略名映射到实际处理方法
    STRATEGY_ALIASES = {
        "auto": "recursive",           # 智能推荐默认使用递归分块
        "naive": "fixed",              # 简单分块映射为固定大小
        "general": "recursive",        # 通用分块映射为递归分块
        "intelligent": "structure",    # 智能分块映射为基于结构
        "parent_child": "recursive",   # 父子分块暂用递归分块（后续可扩展）
        "book": "structure",           # 书籍分块映射为基于结构
        "paper": "structure",          # 论文分块映射为基于结构
        "resume": "structure",         # 简历分块映射为基于结构
        "qa": "recursive",             # 问答对分块暂用递归分块
        "table": "fixed",              # 表格分块映射为固定大小
    }

    @staticmethod
    def get_categories() -> List[str]:
        """获取所有分类"""
        return list(ChunkingService.CATEGORY_CONFIGS.keys())

    @staticmethod
    def add_category(name: str, config: ChunkConfig):
        """添加新分类并持久化"""
        ChunkingService.CATEGORY_CONFIGS[name] = config
        _save_categories()

    @staticmethod
    def recommend_strategy(text: str, title: str = "") -> Dict:
        """使用 LLM 推荐分块策略"""
        prompt = f"""分析以下文档特征，推荐最合适的分块策略。

文档标题: {title}
文档内容前800字:
{text[:800]}

可选策略:
1. fixed - 固定大小分块: 适合日志、格式统一的纯文本
2. recursive - 递归分块: 适合有段落结构的通用文档
3. structure - 基于结构的分块: 适合Markdown、PDF等有明确结构的文档
4. semantic - 语义分块: 适合主题跳跃频繁、对语义完整性要求高的文档
5. naive - 简单分块: 最基础的固定长度切分
6. general - 通用分块: 智能识别段落边界
7. intelligent - 智能分块: 识别标题段落，自动合并过小章节
8. parent_child - 父子分块: 子块用于检索，父块用于上下文
9. book - 书籍分块: 识别章节层级结构
10. paper - 论文分块: 针对学术论文优化
11. resume - 简历分块: 识别简历模块
12. qa - 问答对分块: 识别问答配对
13. table - 表格分块: 保留表格结构

请返回JSON格式:
{{
  "recommended_strategy": "策略名称",
  "reason": "推荐理由",
  "chunk_size": 建议的块大小,
  "overlap": 建议的重叠大小,
  "confidence": "high/medium/low"
}}
"""

        result = LLMService.chat([
            {"role": "system", "content": "你是文档处理专家，擅长分析文档特征并推荐最佳分块策略。只返回JSON。"},
            {"role": "user", "content": prompt}
        ])

        import json
        try:
            import re
            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if json_match:
                recommendation = json.loads(json_match.group())
                return recommendation
        except:
            pass

        return {
            "recommended_strategy": "recursive",
            "reason": "通用文档，使用递归分块作为默认策略",
            "chunk_size": 500,
            "overlap": 100,
            "confidence": "medium"
        }

    @staticmethod
    def chunk_text(text: str, config: Optional[ChunkConfig] = None, category: str = "默认", strategy: str = None) -> List[str]:
        """根据配置进行分块"""
        if config is None:
            config = ChunkingService.CATEGORY_CONFIGS.get(category, ChunkingService.CATEGORY_CONFIGS["默认"])

        # 如果指定了策略，使用指定策略
        if strategy and strategy != "auto":
            # 检查是否有别名映射
            actual_strategy = ChunkingService.STRATEGY_ALIASES.get(strategy, strategy)
            config.strategy = actual_strategy

        if config.strategy == "fixed":
            return ChunkingService._fixed_chunk(text, config.chunk_size, config.overlap)
        elif config.strategy == "recursive":
            return ChunkingService._recursive_chunk(text, config.chunk_size, config.overlap)
        elif config.strategy == "structure":
            return ChunkingService._structure_chunk(text, config.chunk_size, config.overlap)
        elif config.strategy == "semantic":
            return ChunkingService._semantic_chunk(text, config.chunk_size, config.overlap)
        else:
            return ChunkingService._recursive_chunk(text, config.chunk_size, config.overlap)

    @staticmethod
    def _fixed_chunk(text: str, chunk_size: int, overlap: int) -> List[str]:
        """固定大小分块"""
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunk = text[start:end]
            chunks.append(chunk.strip())
            start = end - overlap if end < len(text) else end
        return [c for c in chunks if c]

    @staticmethod
    def _recursive_chunk(text: str, chunk_size: int, overlap: int) -> List[str]:
        """递归分块 - 优先按段落，再按句子"""
        if not text:
            return []

        chunks = []
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        current_chunk = ""

        for para in paragraphs:
            # 如果当前段落加上已有内容不超过限制
            if len(current_chunk) + len(para) < chunk_size:
                current_chunk += para + "\n\n"
            else:
                # 保存当前块
                if current_chunk.strip():
                    chunks.append(current_chunk.strip())

                # 如果段落本身超过限制，需要按句子分割
                if len(para) > chunk_size:
                    sentences = re.split(r'([。！？.!?])', para)
                    current_chunk = ""
                    for i in range(0, len(sentences) - 1, 2):
                        sentence = sentences[i] + (sentences[i+1] if i+1 < len(sentences) else "")

                        if len(current_chunk) + len(sentence) < chunk_size:
                            current_chunk += sentence
                        else:
                            if current_chunk.strip():
                                chunks.append(current_chunk.strip())
                            current_chunk = sentence
                else:
                    current_chunk = para + "\n\n"

        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        return chunks

    @staticmethod
    def _structure_chunk(text: str, chunk_size: int, overlap: int) -> List[str]:
        """基于结构的分块 - 识别标题、章节"""
        # 识别 Markdown 标题、章节标记
        heading_pattern = r'(^#{1,6}\s+.+$)|(^【.+?】$)|(^第[一二三四五六七八九十\d]+[章节].*$)'
        lines = text.split('\n')

        chunks = []
        current_chunk = ""
        current_section = ""

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 检查是否是标题
            if re.match(heading_pattern, line, re.MULTILINE):
                # 保存之前的块
                if current_chunk.strip():
                    chunks.append(current_chunk.strip())
                current_section = line
                current_chunk = line + "\n"
            else:
                if len(current_chunk) + len(line) < chunk_size:
                    current_chunk += line + "\n"
                else:
                    if current_chunk.strip():
                        chunks.append(current_chunk.strip())
                    current_chunk = current_section + "\n" + line + "\n" if current_section else line + "\n"

        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        return [c for c in chunks if c]

    @staticmethod
    def _semantic_chunk(text: str, chunk_size: int, overlap: int) -> List[str]:
        """语义分块 - 基于句子边界和语义连贯性"""
        # 先按句子分割
        sentences = re.split(r'([。！？.!?])', text)

        chunks = []
        current_chunk = ""

        for i in range(0, len(sentences) - 1, 2):
            sentence = sentences[i] + (sentences[i+1] if i+1 < len(sentences) else "")
            sentence = sentence.strip()
            if not sentence:
                continue

            # 检查是否应该在当前句子前分割
            if current_chunk and len(current_chunk) > chunk_size * 0.5:
                # 检查是否有主题转换信号
                transition_signals = ['但是', '然而', '另一方面', '此外', '同时', '另外', '其次', '首先', '最后']
                if any(signal in sentence[:10] for signal in transition_signals):
                    if current_chunk.strip():
                        chunks.append(current_chunk.strip())
                    current_chunk = sentence
                    continue

            if len(current_chunk) + len(sentence) < chunk_size:
                current_chunk += sentence
            else:
                if current_chunk.strip():
                    chunks.append(current_chunk.strip())
                current_chunk = sentence

        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        return [c for c in chunks if c]

# 模块加载时恢复已持久化的自定义分类
_load_categories()

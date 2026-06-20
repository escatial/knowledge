"""
高级文档分块策略（来自 RAG-Pro）
支持 10+ 种分块策略：
- naive: 简单固定宽度
- general: 通用固定大小
- recursive: 递归按分隔符
- intelligent: 智能结构识别
- parent_child: 父子分块
- book: 书籍章节
- paper: 学术论文
- resume: 简历
- qa: 问答对
- table: 表格数据
"""

from dataclasses import dataclass, field
from typing import Literal, List, Optional, Tuple
import re


@dataclass
class DocumentPage:
    """文档页面结构"""
    text: str
    page_number: int | None = None
    section_title: str | None = None
    metadata: dict = field(default_factory=dict)


ChunkMethod = Literal[
    "naive",
    "general",
    "book",
    "paper",
    "resume",
    "table",
    "qa",
    "intelligent",
    "parent_child",
    "recursive",
]


@dataclass
class TextChunk:
    """分块结果"""
    text: str
    chunk_index: int
    page_number: int | None = None
    section_title: str | None = None
    token_count: int = 0
    parent_chunk_index: int | None = None
    metadata: dict = field(default_factory=dict)


def _estimate_tokens(text: str) -> int:
    """
    估算 token 数
    中文：~1.5 字符 / token
    英文：~4 字符 / token
    """
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_chars = len(text) - chinese_chars
    return int(chinese_chars / 1.5 + other_chars / 4)


class RecursiveChunker:
    """
    递归分块器
    按段落 → 句子 → 字符的优先级拆分
    """

    SEPARATORS = ["\n\n", "\n", ". ", "；", "。", " ", ""]

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 64):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def _split_by_separator(self, text: str, separators: List[str]) -> List[str]:
        """递归按分隔符拆分"""
        if not text.strip():
            return []

        if _estimate_tokens(text) <= self.chunk_size:
            return [text]

        if not separators:
            approx_chars = self.chunk_size * 3
            return [text[i:i + approx_chars] for i in range(0, len(text), approx_chars)]

        separator = separators[0]
        remaining_separators = separators[1:]

        if separator == "":
            approx_chars = self.chunk_size * 3
            parts = [text[i:i + approx_chars] for i in range(0, len(text), approx_chars)]
        else:
            parts = text.split(separator)

        result_chunks = []
        current_parts: List[str] = []
        current_tokens = 0

        for part in parts:
            part_tokens = _estimate_tokens(part)

            if part_tokens > self.chunk_size:
                if current_parts:
                    result_chunks.append(separator.join(current_parts))
                    current_parts = []
                    current_tokens = 0
                sub_chunks = self._split_by_separator(part, remaining_separators)
                result_chunks.extend(sub_chunks)
            elif current_tokens + part_tokens > self.chunk_size:
                result_chunks.append(separator.join(current_parts))
                current_parts = [part]
                current_tokens = part_tokens
            else:
                current_parts.append(part)
                current_tokens += part_tokens

        if current_parts:
            result_chunks.append(separator.join(current_parts))

        return result_chunks

    def _add_overlap(self, chunks: List[str]) -> List[str]:
        """添加重叠内容"""
        if len(chunks) <= 1:
            return chunks

        overlap_chars = self.chunk_overlap * 3
        result = []

        for i, chunk in enumerate(chunks):
            if i > 0 and overlap_chars > 0:
                prev_tail = chunks[i - 1][-overlap_chars:]
                chunk = prev_tail + " " + chunk
            result.append(chunk.strip())

        return result

    def chunk_pages(self, pages: List[DocumentPage]) -> List[TextChunk]:
        """拆分文档页面"""
        all_chunks: List[TextChunk] = []
        chunk_index = 0

        for page in pages:
            raw_chunks = self._split_by_separator(page.text, self.SEPARATORS)
            overlapped_chunks = self._add_overlap(raw_chunks)

            for text in overlapped_chunks:
                text = text.strip()
                if not text:
                    continue
                all_chunks.append(TextChunk(
                    text=text,
                    chunk_index=chunk_index,
                    page_number=page.page_number,
                    section_title=page.section_title,
                    token_count=_estimate_tokens(text),
                    metadata=page.metadata,
                ))
                chunk_index += 1

        return all_chunks


class ParentChildChunker:
    """
    父子分块器
    - 子块（512 tokens）：用于检索
    - 父块（1536 tokens）：用于提供上下文
    """

    def __init__(
        self,
        child_chunk_size: int = 512,
        child_overlap: int = 64,
        parent_chunk_size: int = 1536,
    ):
        self.child_chunker = RecursiveChunker(child_chunk_size, child_overlap)
        self.parent_chunker = RecursiveChunker(parent_chunk_size, 0)

    def chunk_pages(self, pages: List[DocumentPage]) -> Tuple[List[TextChunk], List[TextChunk]]:
        """返回 (子块列表, 父块列表)"""
        parent_chunks = self.parent_chunker.chunk_pages(pages)
        child_chunks: List[TextChunk] = []
        child_index = 0

        for parent in parent_chunks:
            temp_page = DocumentPage(
                text=parent.text,
                page_number=parent.page_number,
                section_title=parent.section_title,
                metadata=parent.metadata,
            )
            children = self.child_chunker.chunk_pages([temp_page])

            for child in children:
                child.chunk_index = child_index
                child.parent_chunk_index = parent.chunk_index
                child_chunks.append(child)
                child_index += 1

        return child_chunks, parent_chunks


class IntelligentChunker:
    """智能分块器：识别标题、段落等结构"""

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 64, min_chunk_size: int = 50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size
        self.recursive_chunker = RecursiveChunker(chunk_size, chunk_overlap)

    def chunk_pages(self, pages: List[DocumentPage]) -> List[TextChunk]:
        all_chunks: List[TextChunk] = []
        chunk_index = 0

        for page in pages:
            sections = self._detect_sections(page.text)
            merged_sections = self._merge_small_sections(sections)

            for section in merged_sections:
                if _estimate_tokens(section["text"]) > self.chunk_size:
                    temp_page = DocumentPage(
                        text=section["text"],
                        page_number=page.page_number,
                        section_title=section.get("title") or page.section_title,
                        metadata=page.metadata,
                    )
                    sub_chunks = self.recursive_chunker.chunk_pages([temp_page])
                    for chunk in sub_chunks:
                        chunk.chunk_index = chunk_index
                        all_chunks.append(chunk)
                        chunk_index += 1
                else:
                    all_chunks.append(TextChunk(
                        text=section["text"].strip(),
                        chunk_index=chunk_index,
                        page_number=page.page_number,
                        section_title=section.get("title") or page.section_title,
                        token_count=_estimate_tokens(section["text"]),
                        metadata=page.metadata,
                    ))
                    chunk_index += 1

        return all_chunks

    def _merge_small_sections(self, sections: List[dict]) -> List[dict]:
        """合并过小的章节"""
        if not sections:
            return sections

        merged = []
        i = 0

        while i < len(sections):
            current_section = sections[i].copy()
            current_tokens = _estimate_tokens(current_section["text"])

            while current_tokens < self.min_chunk_size and i + 1 < len(sections):
                i += 1
                next_section = sections[i]
                current_section["text"] += "\n\n" + next_section["text"]
                current_tokens = _estimate_tokens(current_section["text"])

                if not current_section.get("title") and next_section.get("title"):
                    current_section["title"] = next_section["title"]

            merged.append(current_section)
            i += 1

        return merged

    def _detect_sections(self, text: str) -> List[dict]:
        """识别文档章节（标题、段落）"""
        sections = []

        heading_pattern = r'^(#{1,6}\s+.+|第[一二三四五六七八九十\d]+[章节部分].+|[一二三四五六七八九十\d]+[、\.]\s*.+)$'

        lines = text.split('\n')
        current_section = {"title": None, "text": ""}

        for line in lines:
            if re.match(heading_pattern, line.strip()):
                if current_section["text"].strip():
                    sections.append(current_section)
                current_section = {"title": line.strip(), "text": line + "\n"}
            else:
                current_section["text"] += line + "\n"

        if current_section["text"].strip():
            sections.append(current_section)

        return sections if sections else [{"title": None, "text": text}]


class QAChunker:
    """问答对优化分块器"""

    def __init__(self):
        pass

    def chunk_pages(self, pages: List[DocumentPage]) -> List[TextChunk]:
        all_chunks: List[TextChunk] = []
        chunk_index = 0

        for page in pages:
            qa_pairs = self._extract_qa_pairs(page.text)

            for qa in qa_pairs:
                all_chunks.append(TextChunk(
                    text=qa["text"],
                    chunk_index=chunk_index,
                    page_number=page.page_number,
                    section_title=qa.get("question", "")[:50],
                    token_count=_estimate_tokens(qa["text"]),
                    metadata={**page.metadata, "type": "qa"},
                ))
                chunk_index += 1

        return all_chunks

    def _extract_qa_pairs(self, text: str) -> List[dict]:
        """提取问答对"""
        qa_pairs = []

        qa_pattern = r'(?:Q|问|Question)[:：\s]+(.+?)(?:A|答|Answer)[:：\s]+(.+?)(?=(?:Q|问|Question)[:：]|$)'
        matches = re.finditer(qa_pattern, text, re.DOTALL | re.IGNORECASE)

        for match in matches:
            question = match.group(1).strip()
            answer = match.group(2).strip()
            qa_pairs.append({
                "question": question,
                "answer": answer,
                "text": f"Q: {question}\nA: {answer}"
            })

        if not qa_pairs:
            lines = text.strip().split('\n')
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                if ';' in line:
                    pairs = line.split(';')
                    for pair in pairs:
                        if ':' in pair:
                            parts = pair.split(':', 1)
                            if len(parts) == 2:
                                key = parts[0].strip()
                                value = parts[1].strip()
                                if key and value:
                                    qa_pairs.append({
                                        "question": key,
                                        "answer": value,
                                        "text": f"{key}: {value}"
                                    })
                elif ':' in line:
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        key = parts[0].strip()
                        value = parts[1].strip()
                        if key and value:
                            qa_pairs.append({
                                "question": key,
                                "answer": value,
                                "text": f"{key}: {value}"
                            })

        if not qa_pairs:
            numbered_pattern = r'(\d+[、\.]\s*.+?)(?=\d+[、\.]|$)'
            matches = re.finditer(numbered_pattern, text, re.DOTALL)

            for match in matches:
                qa_text = match.group(1).strip()
                qa_pairs.append({
                    "question": qa_text[:100],
                    "text": qa_text
                })

        return qa_pairs if qa_pairs else [{"text": text}]


class TableChunker:
    """表格数据优化分块器"""

    def __init__(self, chunk_size: int = 512):
        self.chunk_size = chunk_size

    def chunk_pages(self, pages: List[DocumentPage]) -> List[TextChunk]:
        all_chunks: List[TextChunk] = []
        chunk_index = 0

        for page in pages:
            if page.metadata.get("headers"):
                lines = page.text.strip().split('\n')
                headers = page.metadata.get("headers", [])

                for line in lines:
                    if not line.strip():
                        continue
                    row_with_context = f"表格数据（列：{', '.join(headers)}）\n{line}"
                    all_chunks.append(TextChunk(
                        text=row_with_context,
                        chunk_index=chunk_index,
                        page_number=page.page_number,
                        section_title=f"数据行 {chunk_index + 1}",
                        token_count=_estimate_tokens(row_with_context),
                        metadata={**page.metadata, "type": "table_row"},
                    ))
                    chunk_index += 1
            else:
                tables = self._extract_tables(page.text)
                if tables:
                    for table in tables:
                        all_chunks.append(TextChunk(
                            text=table["text"],
                            chunk_index=chunk_index,
                            page_number=page.page_number,
                            section_title=f"Table {table['index']}",
                            token_count=_estimate_tokens(table["text"]),
                            metadata={**page.metadata, "type": "table"},
                        ))
                        chunk_index += 1
                else:
                    all_chunks.append(TextChunk(
                        text=page.text,
                        chunk_index=chunk_index,
                        page_number=page.page_number,
                        section_title=page.section_title,
                        token_count=_estimate_tokens(page.text),
                        metadata=page.metadata,
                    ))
                    chunk_index += 1

        return all_chunks

    def _extract_tables(self, text: str) -> List[dict]:
        """提取 Markdown 表格"""
        tables = []
        table_pattern = r'(\|.+\|[\r\n]+\|[-:\s|]+\|[\r\n]+(?:\|.+\|[\r\n]+)+)'
        matches = re.finditer(table_pattern, text)

        for idx, match in enumerate(matches):
            tables.append({
                "index": idx + 1,
                "text": match.group(1).strip()
            })

        return tables


class GeneralChunker:
    """通用固定大小分块器"""

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 64):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_pages(self, pages: List[DocumentPage]) -> List[TextChunk]:
        all_chunks: List[TextChunk] = []
        chunk_index = 0

        for page in pages:
            text = page.text
            approx_chars_per_chunk = self.chunk_size * 3
            overlap_chars = self.chunk_overlap * 3

            start = 0
            while start < len(text):
                end = start + approx_chars_per_chunk
                chunk_text = text[start:end].strip()

                if chunk_text:
                    all_chunks.append(TextChunk(
                        text=chunk_text,
                        chunk_index=chunk_index,
                        page_number=page.page_number,
                        section_title=page.section_title,
                        token_count=_estimate_tokens(chunk_text),
                        metadata=page.metadata,
                    ))
                    chunk_index += 1

                start = end - overlap_chars

        return all_chunks


class NaiveChunker:
    """简单固定宽度分块器"""

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_pages(self, pages: List[DocumentPage]) -> List[TextChunk]:
        all_chunks: List[TextChunk] = []
        chunk_index = 0

        for page in pages:
            text = page.text
            start = 0

            while start < len(text):
                end = start + self.chunk_size
                chunk_text = text[start:end].strip()
                if chunk_text:
                    all_chunks.append(TextChunk(
                        text=chunk_text,
                        chunk_index=chunk_index,
                        page_number=page.page_number,
                        section_title=page.section_title,
                        token_count=_estimate_tokens(chunk_text),
                        metadata={**page.metadata, "method": "naive", "start": start, "end": end},
                    ))
                    chunk_index += 1

                start = end - self.chunk_overlap if self.chunk_overlap > 0 else end

        return all_chunks


class BookChunker:
    """书籍章节分块器"""

    CHAPTER_PATTERN = re.compile(
        r"^(第[一二三四五六七八九十百千万0-9]+[章节部篇]|Chapter\s+\d+|CHAPTER\s+\d+)",
        re.IGNORECASE,
    )

    def __init__(self, max_chunk_size: int = 3000):
        self.max_chunk_size = max_chunk_size

    def chunk_pages(self, pages: List[DocumentPage]) -> List[TextChunk]:
        return self._sectional_chunk(
            pages,
            is_title=self._is_chapter_title,
            section_type="chapter",
            min_length=100,
            max_chunk_size=self.max_chunk_size,
        )

    def _is_chapter_title(self, line: str) -> bool:
        if self.CHAPTER_PATTERN.match(line):
            return True
        return len(line) < 50 and line and not line.endswith(("。", "！", "？", ".", "!", "?", "，", ","))

    def _sectional_chunk(
        self,
        pages: List[DocumentPage],
        is_title,
        section_type: str,
        min_length: int,
        max_chunk_size: int,
    ) -> List[TextChunk]:
        chunks: List[TextChunk] = []
        chunk_index = 0

        for page in pages:
            lines = page.text.split("\n")
            current_title = page.section_title
            current_lines: List[str] = []

            for raw_line in lines:
                line = raw_line.strip()
                if not line:
                    continue

                if is_title(line):
                    if current_lines:
                        content = "\n".join(current_lines).strip()
                        if len(content) > min_length:
                            chunks.append(TextChunk(
                                text=content,
                                chunk_index=chunk_index,
                                page_number=page.page_number,
                                section_title=current_title,
                                token_count=_estimate_tokens(content),
                                metadata={**page.metadata, "type": section_type, "title": current_title or "未命名章节"},
                            ))
                            chunk_index += 1
                    current_title = line
                    current_lines = [line]
                    continue

                current_lines.append(line)

                if sum(len(item) for item in current_lines) > max_chunk_size:
                    content = "\n".join(current_lines).strip()
                    chunks.append(TextChunk(
                        text=content,
                        chunk_index=chunk_index,
                        page_number=page.page_number,
                        section_title=current_title,
                        token_count=_estimate_tokens(content),
                        metadata={**page.metadata, "type": section_type, "title": current_title or "未命名章节"},
                    ))
                    chunk_index += 1
                    current_lines = []

            if current_lines:
                content = "\n".join(current_lines).strip()
                if len(content) > min_length:
                    chunks.append(TextChunk(
                        text=content,
                        chunk_index=chunk_index,
                        page_number=page.page_number,
                        section_title=current_title,
                        token_count=_estimate_tokens(content),
                        metadata={**page.metadata, "type": section_type, "title": current_title or "未命名章节"},
                    ))
                    chunk_index += 1

        return chunks


class PaperChunker:
    """学术论文分块器"""

    SECTION_KEYWORDS = [
        "abstract", "摘要", "introduction", "引言", "绪论",
        "related work", "相关工作", "methodology", "方法", "方法论",
        "experiment", "实验", "result", "结果", "discussion", "讨论",
        "conclusion", "结论", "reference", "参考文献", "acknowledgment", "致谢",
    ]

    def chunk_pages(self, pages: List[DocumentPage]) -> List[TextChunk]:
        return self._keyword_section_chunk(
            pages,
            keywords=self.SECTION_KEYWORDS,
            section_type="paper_section",
            title_max_length=100,
            min_length=50,
        )

    def _keyword_section_chunk(
        self,
        pages: List[DocumentPage],
        keywords: List[str],
        section_type: str,
        title_max_length: int,
        min_length: int,
    ) -> List[TextChunk]:
        chunks: List[TextChunk] = []
        chunk_index = 0

        for page in pages:
            current_title = page.section_title
            current_lines: List[str] = []

            for raw_line in page.text.split("\n"):
                line = raw_line.strip()
                if not line:
                    continue

                line_lower = line.lower()
                is_section = any(keyword in line_lower for keyword in keywords) and len(line) < title_max_length

                if is_section:
                    if current_lines:
                        content = "\n".join(current_lines).strip()
                        if len(content) > min_length:
                            chunks.append(TextChunk(
                                text=content,
                                chunk_index=chunk_index,
                                page_number=page.page_number,
                                section_title=current_title,
                                token_count=_estimate_tokens(content),
                                metadata={**page.metadata, "type": section_type, "section": current_title or "未命名"},
                            ))
                            chunk_index += 1
                    current_title = line
                    current_lines = [line]
                else:
                    current_lines.append(line)

            if current_lines:
                content = "\n".join(current_lines).strip()
                if len(content) > min_length:
                    chunks.append(TextChunk(
                        text=content,
                        chunk_index=chunk_index,
                        page_number=page.page_number,
                        section_title=current_title,
                        token_count=_estimate_tokens(content),
                        metadata={**page.metadata, "type": section_type, "section": current_title or "未命名"},
                    ))
                    chunk_index += 1

        return chunks


class ResumeChunker:
    """简历分块器"""

    SECTION_KEYWORDS = [
        "个人信息", "基本信息", "personal", "contact",
        "教育背景", "教育经历", "education",
        "工作经历", "工作经验", "experience", "employment",
        "项目经验", "项目经历", "project",
        "技能", "专业技能", "skill",
        "证书", "资格证书", "certificate",
        "自我评价", "summary", "objective",
    ]

    def chunk_pages(self, pages: List[DocumentPage]) -> List[TextChunk]:
        return PaperChunker()._keyword_section_chunk(
            pages,
            keywords=self.SECTION_KEYWORDS,
            section_type="resume_section",
            title_max_length=50,
            min_length=20,
        )


def get_chunker(
    method: ChunkMethod,
    chunk_size: int = 512,
    chunk_overlap: int = 64,
    min_chunk_size: int = 50
):
    """
    获取分块器工厂函数
    
    Args:
        method: 分块策略
        chunk_size: 目标块大小（token）
        chunk_overlap: 重叠大小（token）
        min_chunk_size: 最小块大小（intelligent 策略用）
    
    Returns:
        分块器实例
    """
    if method == "naive":
        return NaiveChunker(chunk_size, chunk_overlap)
    elif method == "book":
        return BookChunker(max_chunk_size=max(chunk_size * 3, 1500))
    elif method == "paper":
        return PaperChunker()
    elif method == "resume":
        return ResumeChunker()
    elif method == "intelligent":
        return IntelligentChunker(chunk_size, chunk_overlap, min_chunk_size)
    elif method == "qa":
        return QAChunker()
    elif method == "table":
        return TableChunker(chunk_size)
    elif method == "general":
        return GeneralChunker(chunk_size, chunk_overlap)
    elif method == "parent_child":
        return ParentChildChunker(chunk_size, chunk_overlap)
    elif method == "recursive":
        return RecursiveChunker(chunk_size, chunk_overlap)
    else:
        raise ValueError(f"Unknown chunk method: {method}")

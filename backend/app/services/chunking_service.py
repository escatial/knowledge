"""
统一分块服务
根据配置自动选择基础版或高级版分块器
保持向后兼容，同时提供增强功能
"""

from typing import List, Optional, Union
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.core.chunking import ChunkingService, ChunkConfig


# 尝试导入高级分块器（可选）
try:
    from app.core.advanced_chunking import (
        get_chunker,
        ChunkMethod,
        TextChunk,
        DocumentPage as AdvancedDocumentPage
    )
    from app.core.document_parser_v2 import DocumentParserV2
    HAS_ADVANCED = True
except ImportError as e:
    HAS_ADVANCED = False
    print(f"Warning: Advanced chunking not available: {e}")


@dataclass
class ChunkResult:
    """统一的分块结果"""
    text: str
    chunk_index: int
    page_number: Optional[int] = None
    section_title: Optional[str] = None
    metadata: dict = None
    token_count: int = 0


class UnifiedChunkingService:
    """统一分块服务"""

    @staticmethod
    def is_advanced_available() -> bool:
        """检查高级分块器是否可用"""
        return HAS_ADVANCED and getattr(settings, "USE_ADVANCED_CHUNKING", True)

    @staticmethod
    def chunk_text(
        text: str,
        strategy: Optional[str] = None,
        chunk_size: Optional[int] = None,
        overlap: Optional[int] = None,
        category: str = "默认"
    ) -> List[str]:
        """
        分块纯文本（向后兼容接口）
        
        Args:
            text: 要分块的文本
            strategy: 分块策略
            chunk_size: 块大小
            overlap: 重叠大小
            category: 分类
        
        Returns:
            文本块列表
        """
        if UnifiedChunkingService.is_advanced_available():
            # 使用高级分块器
            return UnifiedChunkingService._chunk_with_advanced(
                text, strategy, chunk_size, overlap
            )
        else:
            # 使用基础分块器
            config = ChunkConfig(
                strategy=strategy or "recursive",
                chunk_size=chunk_size or 500,
                overlap=overlap or 100
            )
            return ChunkingService.chunk_text(text, config=config, category=category)

    @staticmethod
    def _chunk_with_advanced(
        text: str,
        strategy: Optional[str] = None,
        chunk_size: Optional[int] = None,
        overlap: Optional[int] = None
    ) -> List[str]:
        """使用高级分块器分块纯文本"""
        method: ChunkMethod = strategy or "recursive"
        chunker = get_chunker(
            method,
            chunk_size=chunk_size or 512,
            chunk_overlap=overlap or 64
        )
        page = AdvancedDocumentPage(text=text)
        chunks = chunker.chunk_pages([page])
        return [c.text for c in chunks]

    @staticmethod
    def chunk_file(
        file_path: Union[str, Path],
        strategy: Optional[str] = None,
        chunk_size: Optional[int] = None,
        overlap: Optional[int] = None,
        use_advanced: Optional[bool] = None
    ) -> List[ChunkResult]:
        """
        分块文档文件
        
        Args:
            file_path: 文件路径
            strategy: 分块策略
            chunk_size: 块大小
            overlap: 重叠大小
            use_advanced: 是否使用高级版（None 则根据配置）
        
        Returns:
            ChunkResult 列表
        """
        if use_advanced is None:
            use_advanced = UnifiedChunkingService.is_advanced_available()

        if use_advanced and HAS_ADVANCED:
            return UnifiedChunkingService._chunk_file_advanced(
                str(file_path), strategy, chunk_size, overlap
            )
        else:
            return UnifiedChunkingService._chunk_file_basic(str(file_path))

    @staticmethod
    def _chunk_file_advanced(
        file_path: str,
        strategy: Optional[str] = None,
        chunk_size: Optional[int] = None,
        overlap: Optional[int] = None
    ) -> List[ChunkResult]:
        """使用高级版分块文件"""
        parser = DocumentParserV2()
        pages = parser.parse_file(file_path)
        
        method: ChunkMethod = strategy or "recursive"
        chunker = get_chunker(
            method,
            chunk_size=chunk_size or 512,
            chunk_overlap=overlap or 64
        )
        
        text_chunks = chunker.chunk_pages(pages)
        
        return [
            ChunkResult(
                text=tc.text,
                chunk_index=tc.chunk_index,
                page_number=tc.page_number,
                section_title=tc.section_title,
                metadata=tc.metadata,
                token_count=tc.token_count
            )
            for tc in text_chunks
        ]

    @staticmethod
    def _chunk_file_basic(file_path: str) -> List[ChunkResult]:
        """使用基础版分块文件"""
        from app.services.document_parser import DocumentParser
        
        parser = DocumentParser()
        text = parser.parse_bytes(Path(file_path).read_bytes(), Path(file_path).name)
        chunks = ChunkingService.chunk_text(text)
        
        return [
            ChunkResult(
                text=chunk,
                chunk_index=i,
                metadata={"source": Path(file_path).name}
            )
            for i, chunk in enumerate(chunks)
        ]

    @staticmethod
    def chunk_bytes(
        content: bytes,
        filename: str,
        strategy: Optional[str] = None,
        chunk_size: Optional[int] = None,
        overlap: Optional[int] = None,
        use_advanced: Optional[bool] = None
    ) -> List[ChunkResult]:
        """
        从字节内容分块
        
        Args:
            content: 文件字节内容
            filename: 文件名
            strategy: 分块策略
            chunk_size: 块大小
            overlap: 重叠大小
            use_advanced: 是否使用高级版
        
        Returns:
            ChunkResult 列表
        """
        if use_advanced is None:
            use_advanced = UnifiedChunkingService.is_advanced_available()

        if use_advanced and HAS_ADVANCED:
            return UnifiedChunkingService._chunk_bytes_advanced(
                content, filename, strategy, chunk_size, overlap
            )
        else:
            return UnifiedChunkingService._chunk_bytes_basic(content, filename)

    @staticmethod
    def _chunk_bytes_advanced(
        content: bytes,
        filename: str,
        strategy: Optional[str] = None,
        chunk_size: Optional[int] = None,
        overlap: Optional[int] = None
    ) -> List[ChunkResult]:
        """使用高级版分块字节内容"""
        parser = DocumentParserV2()
        pages = parser.parse_bytes(content, filename)
        
        method: ChunkMethod = strategy or "recursive"
        chunker = get_chunker(
            method,
            chunk_size=chunk_size or 512,
            chunk_overlap=overlap or 64
        )
        
        text_chunks = chunker.chunk_pages(pages)
        
        return [
            ChunkResult(
                text=tc.text,
                chunk_index=tc.chunk_index,
                page_number=tc.page_number,
                section_title=tc.section_title,
                metadata=tc.metadata,
                token_count=tc.token_count
            )
            for tc in text_chunks
        ]

    @staticmethod
    def _chunk_bytes_basic(content: bytes, filename: str) -> List[ChunkResult]:
        """使用基础版分块字节内容"""
        from app.services.document_parser import DocumentParser
        
        parser = DocumentParser()
        text = parser.parse_bytes(content, filename)
        chunks = ChunkingService.chunk_text(text)
        
        return [
            ChunkResult(
                text=chunk,
                chunk_index=i,
                metadata={"source": filename}
            )
            for i, chunk in enumerate(chunks)
        ]

    @staticmethod
    def get_available_strategies() -> List[str]:
        """获取可用的分块策略列表"""
        base_strategies = ["fixed", "recursive", "structure", "semantic"]
        
        if HAS_ADVANCED:
            advanced_strategies = [
                "naive", "general", "recursive", "intelligent",
                "parent_child", "book", "paper", "resume", "qa", "table"
            ]
            return list(dict.fromkeys(base_strategies + advanced_strategies))
        else:
            return base_strategies


# 便捷函数
def chunk_text(
    text: str,
    strategy: Optional[str] = None,
    chunk_size: Optional[int] = None,
    overlap: Optional[int] = None
) -> List[str]:
    """便捷函数：分块文本"""
    return UnifiedChunkingService.chunk_text(
        text, strategy, chunk_size, overlap
    )


def chunk_file(
    file_path: Union[str, Path],
    strategy: Optional[str] = None,
    chunk_size: Optional[int] = None,
    overlap: Optional[int] = None
) -> List[ChunkResult]:
    """便捷函数：分块文件"""
    return UnifiedChunkingService.chunk_file(
        file_path, strategy, chunk_size, overlap
    )


def chunk_bytes(
    content: bytes,
    filename: str,
    strategy: Optional[str] = None,
    chunk_size: Optional[int] = None,
    overlap: Optional[int] = None
) -> List[ChunkResult]:
    """便捷函数：分块字节内容"""
    return UnifiedChunkingService.chunk_bytes(
        content, filename, strategy, chunk_size, overlap
    )

"""
文档解析服务
支持 PDF、DOCX、TXT、MD 等格式
"""
import io
from pathlib import Path


class DocumentParser:
    """文档解析器"""
    
    @staticmethod
    def parse_bytes(content: bytes, filename: str) -> str:
        """解析文档内容（从 bytes）"""
        filename_lower = filename.lower()
        
        if filename_lower.endswith('.pdf'):
            return DocumentParser._parse_pdf(content)
        elif filename_lower.endswith('.docx'):
            return DocumentParser._parse_docx(content)
        elif filename_lower.endswith(('.txt', '.md', '.json', '.py', '.js', '.ts', '.tsx', '.html', '.css')):
            return DocumentParser._parse_text(content)
        else:
            # 尝试作为文本解析
            return DocumentParser._parse_text(content)
    
    @staticmethod
    def _parse_pdf(content: bytes) -> str:
        """解析 PDF"""
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(io.BytesIO(content))
            text = ""
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
            return text if text else "[PDF 无文本内容]"
        except Exception as e:
            return f"[PDF 解析失败: {str(e)}]"
    
    @staticmethod
    def _parse_docx(content: bytes) -> str:
        """解析 DOCX"""
        try:
            from docx import Document
            doc = Document(io.BytesIO(content))
            text = ""
            for para in doc.paragraphs:
                text += para.text + "\n"
            return text if text else "[DOCX 无文本内容]"
        except Exception as e:
            return f"[DOCX 解析失败: {str(e)}]"
    
    @staticmethod
    def _parse_text(content: bytes) -> str:
        """解析文本文件"""
        import chardet
        detected = chardet.detect(content)
        encoding = detected.get('encoding', 'utf-8') or 'utf-8'
        try:
            return content.decode(encoding)
        except:
            try:
                return content.decode('utf-8')
            except:
                return content.decode('utf-8', errors='ignore')

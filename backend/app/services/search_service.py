"""
搜索服务
"""
from typing import List

from app.models.document import SearchResult, Answer, Document
from app.services.document_service import _documents


class SearchService:
    def search(self, query: str, limit: int = 10) -> List[SearchResult]:
        """简单关键词搜索（生产环境应使用向量数据库）"""
        results = []
        query_lower = query.lower()
        
        for doc in _documents.values():
            score = self._calculate_score(query_lower, doc.content.lower())
            if score > 0:
                # 提取片段
                snippet = self._extract_snippet(doc.content, query)
                results.append(SearchResult(
                    document=doc,
                    score=score,
                    snippet=snippet
                ))
        
        # 按分数排序
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:limit]
    
    def _calculate_score(self, query: str, content: str) -> float:
        """计算匹配分数"""
        if query in content:
            return 1.0
        # 简单分词匹配
        query_words = set(query.split())
        content_words = set(content.split())
        overlap = len(query_words & content_words)
        return overlap / len(query_words) if query_words else 0
    
    def _extract_snippet(self, content: str, query: str, length: int = 200) -> str:
        """提取包含关键词的文本片段"""
        idx = content.lower().find(query.lower())
        if idx == -1:
            return content[:length]
        start = max(0, idx - length // 2)
        end = min(len(content), idx + length // 2)
        return content[start:end]
    
    def ask(self, question: str) -> Answer:
        """RAG 问答（简化版）"""
        # 搜索相关文档
        results = self.search(question, limit=5)
        
        # 构建答案（实际应调用 LLM）
        if not results:
            return Answer(
                question=question,
                answer="未找到相关知识。",
                sources=[]
            )
        
        # 简单拼接作为答案
        context = "\n".join([r.snippet for r in results[:3]])
        answer = f"基于知识库内容：\n\n{context}"
        
        return Answer(
            question=question,
            answer=answer,
            sources=[r.document for r in results]
        )

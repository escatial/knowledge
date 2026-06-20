"""
LLM 服务封装 - 支持多模型配置
"""
from typing import Iterator, Optional
from openai import OpenAI

from app.core.config import settings


class LLMService:
    """LLM 服务 - 支持动态切换模型"""

    @staticmethod
    def resolve_config(model: Optional[str] = None, api_key: Optional[str] = None, base_url: Optional[str] = None):
        """根据模型名称自动解析对应的 API 配置"""
        if api_key and base_url:
            return api_key, base_url

        if model:
            model_lower = model.lower()
            # DeepSeek 模型
            if 'deepseek' in model_lower:
                return settings.DEEPSEEK_API_KEY, settings.DEEPSEEK_BASE_URL

        # 默认使用 MiniMax
        return settings.OPENAI_API_KEY, settings.OPENAI_BASE_URL

    @staticmethod
    def get_client(api_key: Optional[str] = None, base_url: Optional[str] = None):
        """获取 OpenAI 客户端"""
        if not api_key:
            return None

        return OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=60,
        )

    @staticmethod
    def chat(messages: list, stream: bool = False, model: Optional[str] = None, api_key: Optional[str] = None, base_url: Optional[str] = None) -> str | Iterator[str]:
        """对话 - 支持指定模型"""
        resolved_key, resolved_url = LLMService.resolve_config(model, api_key, base_url)
        client = LLMService.get_client(resolved_key, resolved_url)

        if not client:
            return "[LLM 未配置，请设置 API Key]"

        # 使用指定的模型或默认模型
        model_name = model or settings.OPENAI_MODEL

        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                stream=stream,
                temperature=0.7,
                max_tokens=2000,
            )

            if stream:
                def generator():
                    for chunk in response:
                        if chunk.choices[0].delta.content:
                            yield chunk.choices[0].delta.content
                return generator()

            return response.choices[0].message.content
        except Exception as e:
            return f"[LLM 调用失败: {str(e)}]"
    
    @staticmethod
    def extract_entities(text: str, model: Optional[str] = None) -> dict:
        """从文本中提取实体和关系"""
        prompt = f"""从以下文本中提取实体和关系，返回 JSON 格式。

要求：
1. 实体类型包括：人物、组织、地点、概念、技术、产品、事件
2. 关系类型包括：属于、创建、使用、位于、参与、相关、包含
3. 只提取重要的实体和关系

文本：
{text[:3000]}

返回格式：
{{
  "entities": [
    {{"id": "e1", "name": "实体名称", "type": "人物|组织|地点|概念|技术|产品|事件", "description": "简要描述"}}
  ],
  "relations": [
    {{"source": "e1", "target": "e2", "type": "关系类型", "description": "关系描述"}}
  ]
}}
"""
        result = LLMService.chat([
            {"role": "system", "content": "你是一个知识图谱构建专家，擅长从文本中提取实体和关系。只返回 JSON，不要其他内容。"},
            {"role": "user", "content": prompt}
        ], model=model)
        
        # 解析 JSON
        import json
        import re
        try:
            # 提取 JSON 部分
            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except:
            pass
        
        return {"entities": [], "relations": []}
    
    @staticmethod
    def answer_question(question: str, context: str, model: Optional[str] = None) -> str:
        """基于上下文回答问题"""
        prompt = f"""基于以下知识库内容回答问题。如果知识库中没有相关信息，请明确说明。

知识库内容：
{context[:4000]}

问题：{question}

请给出准确、简洁的回答。"""
        
        return LLMService.chat([
            {"role": "system", "content": "你是一个知识库助手，基于提供的知识回答问题。"},
            {"role": "user", "content": prompt}
        ], model=model)

    @staticmethod
    def classify_entities(prompt: str, model: Optional[str] = None) -> dict:
        """任务 4：调用 LLM 对实体列表进行价值分类

        Args:
            prompt: 包含实体列表和分类标准的完整 prompt
            model: 指定模型

        Returns:
            {
                "domain_vocabulary": [...],
                "classifications": [...]
            }
        """
        import re
        result = LLMService.chat([
            {"role": "system", "content": "你是一个知识图谱质量审核专家。只返回 JSON，不要其他内容。"},
            {"role": "user", "content": prompt}
        ], model=model)

        try:
            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception as e:
            logger = __import__('logging').getLogger(__name__)
            logger.warning(f"[LLM] classify_entities JSON 解析失败: {e}\n原始响应: {result[:200]}")

        return {"domain_vocabulary": [], "classifications": []}

    @staticmethod
    def extract_cross_doc_relations(prompt: str, model: Optional[str] = None) -> dict:
        """任务 3：调用 LLM 分析跨文档实体关联

        Args:
            prompt: 包含候选实体对列表的完整 prompt
            model: 指定模型

        Returns:
            {"relations": [{"pair_index": int, "decision": str, "relation_type": str, "reason": str}]}
        """
        import re
        result = LLMService.chat([
            {"role": "system", "content": "你是一个知识图谱关联分析专家。只返回 JSON，不要其他内容。"},
            {"role": "user", "content": prompt}
        ], model=model)

        try:
            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception as e:
            logger = __import__('logging').getLogger(__name__)
            logger.warning(f"[LLM] extract_cross_doc_relations JSON 解析失败: {e}")

        return {"relations": []}

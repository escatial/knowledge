"""
嵌入服务 - 支持多种模式

支持的 Embedding 模式：
1. local       - 本地 sentence-transformers 模型（推荐 BAAI/bge-small-zh-v1.5）
2. api         - 调用 LLM 厂商的 OpenAI 兼容 Embedding 接口
                支持的厂商：openai / deepseek / minimax / qwen / zhipu / ollama / custom
3. modelscope  - ModelScope 国内镜像（保留旧能力）

通过环境变量切换：
    EMBEDDING_MODE=api EMBEDDING_PROVIDER=minimax  # 走 MiniMax 的 embo-01
    EMBEDDING_MODE=api EMBEDDING_PROVIDER=qwen      # 走通义千问
    EMBEDDING_MODE=api EMBEDDING_PROVIDER=openai    # 走 OpenAI 官方
    EMBEDDING_MODE=api EMBEDDING_PROVIDER=ollama    # 走本地 Ollama
    EMBEDDING_MODE=local USE_REAL_EMBEDDING=1       # 启用本地真实模型
"""
import os
import hashlib
import math
import re
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any

from app.core.config import settings, EMBEDDING_PROVIDERS


class BaseEmbedding(ABC):
    """嵌入基类"""

    @abstractmethod
    def encode(self, texts: List[str]) -> List[List[float]]:
        """编码文本为向量"""
        pass

    def encode_query(self, texts: List[str]) -> List[List[float]]:
        """编码查询文本（部分 provider 区分入库/检索算法）
        默认实现：复用 encode。MiniMax 等会覆盖此方法以传 type='query'。
        """
        return self.encode(texts)

    @abstractmethod
    def dimension(self) -> int:
        """返回向量维度"""
        pass

    @abstractmethod
    def mode(self) -> str:
        """返回当前模式标识"""
        pass

    def info(self) -> Dict[str, Any]:
        """返回当前 embedding 服务的可读信息"""
        return {
            "mode": self.mode(),
            "dimension": self.dimension(),
        }


class LocalEmbedding(BaseEmbedding):
    """本地 BGE 嵌入（transformers + torch 直加载）+ 哈希回退

    加载策略（4 层降级）：
    1. BAAI/bge-small-zh-v1.5 本地路径（首选，离线）
    2. ModelScope 平台（线上预留，未来服务器用）
    3. sentence-transformers 在线（备用，需联网）
    4. 哈希伪向量（最后保底，不丢服务）
    """

    # BGE 官方 query 前缀（用于检索任务，提升召回率）
    BGE_QUERY_PREFIX = "为这个句子生成表示以用于检索中文文档："

    def __init__(self):
        self._use_real = os.getenv("USE_REAL_EMBEDDING", "1") == "1"  # 默认启用 BGE
        self._model = None
        self._tokenizer = None
        self._device = "cpu"  # 默认 CPU（无 GPU 时）
        self._dim = 512  # bge-small-zh-v1.5 固定 512 维
        self._backend = "hash_fallback"  # 实际生效的后端

        if self._use_real:
            self._try_load_real_model()
        else:
            print("[Embedding] USE_REAL_EMBEDDING=0，使用哈希回退")

    def _try_load_real_model(self):
        """按优先级尝试加载真实模型"""
        local_model_path = os.path.join(
            settings.MODEL_DIR, settings.EMBEDDING_MODEL_NAME.replace("/", "_")
        )

        # 优先级 1: 本地 transformers 直加载（最稳，避免 sentence_transformers 兼容问题）
        if os.path.exists(local_model_path):
            if self._try_load_with_transformers(local_model_path):
                return
            print(f"[Embedding] transformers 加载本地失败，尝试 sentence_transformers")
            # 优先级 2: sentence_transformers（如果 transformers 直加载失败）
            if self._try_load_with_sentence_transformers(local_model_path):
                return

        # 优先级 3: 在线下载 sentence_transformers（需联网）
        try:
            from sentence_transformers import SentenceTransformer
            print(f"[Embedding] 在线下载: {settings.EMBEDDING_MODEL_NAME}")
            self._model = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)
            self._backend = "sentence_transformers_remote"
            # 缓存到本地
            try:
                if os.path.exists(local_model_path):
                    import shutil
                    shutil.rmtree(local_model_path)
                self._model.save(local_model_path)
            except Exception as e:
                print(f"[Embedding] 缓存到本地失败（不影响使用）: {e}")
        except Exception as e:
            print(f"[Embedding] sentence_transformers 在线加载失败: {e}")

    def _try_load_with_transformers(self, model_path: str) -> bool:
        """方案 1：用 transformers + torch 直接加载"""
        try:
            import torch
            from transformers import AutoTokenizer, AutoModel

            self._tokenizer = AutoTokenizer.from_pretrained(model_path)
            self._model = AutoModel.from_pretrained(model_path)
            self._model.eval()

            # 优先使用 GPU
            if torch.cuda.is_available():
                self._device = "cuda"
                self._model = self._model.to(self._device)
            else:
                self._device = "cpu"

            self._dim = self._model.config.hidden_size
            self._backend = "transformers_local"
            # 任务 X：修复误导性日志（实际可能是 Qwen3 而非 BGE）
            model_basename = os.path.basename(model_path.rstrip("/\\"))
            print(f"[Embedding] 加载成功 (transformers, {self._device}, dim={self._dim}, model={model_basename})")
            return True
        except Exception as e:
            print(f"[Embedding] transformers 加载失败: {type(e).__name__}: {e}")
            self._model = None
            self._tokenizer = None
            return False

    def _try_load_with_sentence_transformers(self, model_path: str) -> bool:
        """方案 2：用 sentence_transformers 加载（备用）"""
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(model_path)
            self._dim = self._model.get_sentence_embedding_dimension()
            self._backend = "sentence_transformers_local"
            model_basename = os.path.basename(model_path.rstrip("/\\"))
            print(f"[Embedding] 加载成功 (sentence_transformers, dim={self._dim}, model={model_basename})")
            return True
        except Exception as e:
            print(f"[Embedding] sentence_transformers 加载失败: {e}")
            self._model = None
            return False

    def _bge_encode_transformers(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """使用 transformers 编码（CLS pooling + L2 normalize）"""
        import torch
        all_vecs = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            # 处理空字符串
            batch = [t if t and t.strip() else " " for t in batch]
            inputs = self._tokenizer(
                batch, padding=True, truncation=True,
                max_length=512, return_tensors="pt"
            )
            inputs = {k: v.to(self._device) for k, v in inputs.items()}
            with torch.no_grad():
                outputs = self._model(**inputs)
            # BGE 标准：CLS token (last_hidden_state[:, 0])
            embeddings = outputs.last_hidden_state[:, 0]
            # L2 归一化
            embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)
            all_vecs.append(embeddings.cpu().numpy())
        import numpy as np
        return np.concatenate(all_vecs, axis=0).tolist()

    def encode(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        # 后端分发
        if self._backend == "transformers_local" and self._model is not None:
            try:
                return self._bge_encode_transformers(texts)
            except Exception as e:
                print(f"[Embedding] BGE 编码失败，回退到 hash: {e}")
                return [self._hash_embed(t) for t in texts]
        if self._backend in ("sentence_transformers_local", "sentence_transformers_remote") and self._model is not None:
            try:
                vecs = self._model.encode(texts, normalize_embeddings=True)
                return vecs.tolist() if hasattr(vecs, "tolist") else list(vecs)
            except Exception as e:
                print(f"[Embedding] sentence_transformers 编码失败: {e}")
                return [self._hash_embed(t) for t in texts]
        # 哈希回退
        return [self._hash_embed(t) for t in texts]

    def encode_query(self, texts: List[str]) -> List[List[float]]:
        """BGE query 编码：必须加前缀以提升检索质量"""
        if isinstance(texts, str):
            texts = [texts]
        if self._backend in ("transformers_local", "sentence_transformers_local", "sentence_transformers_remote"):
            prefixed = [self.BGE_QUERY_PREFIX + (t or "") for t in texts]
            return self.encode(prefixed)
        # 哈希回退：query 与 doc 相同
        return self.encode(texts)

    def dimension(self) -> int:
        return self._dim

    def mode(self) -> str:
        return self._backend if self._backend != "hash_fallback" else "local_hash_fallback"

    def info(self) -> Dict[str, Any]:
        return {
            "mode": self.mode(),
            "dimension": self.dimension(),
            "device": self._device if self._backend == "transformers_local" else "n/a",
            "model_name": settings.EMBEDDING_MODEL_NAME if self._model else "(hash fallback)",
            "supports_chinese": True,
        }

    @staticmethod
    def _hash_embed(text: str, dim: int = 512) -> List[float]:
        """轻量级嵌入：基于词 + 字符 n-gram 特征哈希生成伪向量，保留较高的文本相似度。"""
        vec = [0.0] * dim
        if not text:
            return vec

        text_clean = text.strip()
        if not text_clean:
            return vec

        tokens = set()
        # 单字
        for ch in text_clean:
            if ch.strip():
                tokens.add(f"c:{ch}")
        # 2-gram
        for i in range(len(text_clean) - 1):
            bigram = text_clean[i:i+2]
            if bigram.strip():
                tokens.add(f"b:{bigram}")
        # 词
        words = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+", text_clean)
        for w in words:
            if w.strip():
                tokens.add(f"w:{w.lower()}")

        for tok in tokens:
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest()[:8], 16)
            idx = h % dim
            sign = 1 if (h & 0x80000000) == 0 else -1
            vec[idx] += sign

        norm = math.sqrt(sum(v * v for v in vec)) + 1e-8
        return [v / norm for v in vec]


class APIEmbedding(BaseEmbedding):
    """API 嵌入 - 支持所有 LLM 厂商的 OpenAI 兼容 Embedding 接口

    通过 EMBEDDING_PROVIDER 环境变量切换：
        - openai      OpenAI 官方
        - deepseek    DeepSeek (暂未提供，可走中转)
        - minimax     MiniMax  embo-01 (自研协议: 需 GroupId + type=db/query)
        - qwen        通义千问 DashScope  text-embedding-v3
        - zhipu       智谱 GLM  embedding-2
        - ollama      本地 Ollama
        - custom      自定义 OpenAI 兼容服务
    """

    def __init__(self, provider: Optional[str] = None):
        self.provider = (provider or settings.EMBEDDING_PROVIDER or "minimax").lower()
        if self.provider not in EMBEDDING_PROVIDERS:
            raise ValueError(
                f"未知的 Embedding provider: {self.provider}。"
                f"可选: {list(EMBEDDING_PROVIDERS.keys())}"
            )
        self.provider_info = EMBEDDING_PROVIDERS[self.provider]
        self.protocol = self.provider_info.get("protocol", "openai")

        # 解析 base_url / model / api_key
        self.base_url = self._resolve_base_url()
        self.api_key = self._resolve_api_key()
        self.model = (
            settings.EMBEDDING_MODEL_OVERRIDE
            or self.provider_info["default_model"]
        )
        self._expected_dim = self.provider_info["dim"]

        # MiniMax 协议额外需要 GroupId
        self.group_id = self._resolve_group_id()

        # 校验
        if not self.provider_info["supports_embedding"]:
            print(
                f"[Embedding] ⚠️ {self.provider_info['label']} 未官方提供 embedding 端点，"
                f"将尝试调用其 OpenAI 兼容 /embeddings 接口（可能成功也可能失败）"
            )

        # MiniMax 协议校验：未传 GroupId 时主动降级
        if self.protocol == "minimax" and not self.group_id:
            print(
                f"[Embedding] ⚠️ MiniMax 自研协议需要 GroupId（环境变量 MiniMax_GROUP_ID），"
                f"未配置时降级为 hash 回退"
            )

        if not self.api_key:
            # 自动降级
            if settings.EMBEDDING_FALLBACK == "error":
                raise RuntimeError(
                    f"未配置 {self.provider_info['api_key_env']}，且 EMBEDDING_FALLBACK=error，拒绝启动"
                )
            print(
                f"[Embedding] ⚠️ 未配置 {self.provider_info['api_key_env']}，"
                f"将降级使用哈希伪向量（语义质量会大幅下降）"
            )
            self._client = None
        else:
            from openai import OpenAI
            # Ollama 兼容 OpenAI 协议时使用任意 key 即可
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=60,
            )
            # MiniMax 协议：初始化 requests session 用于自定义请求
            if self.protocol == "minimax":
                import requests
                self._session = requests.Session()
                self._session.headers.update({
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                })
            print(
                f"[Embedding] API 模式 | provider={self.provider_info['label']} | "
                f"protocol={self.protocol} | model={self.model} | base_url={self.base_url}"
            )

    def _resolve_base_url(self) -> str:
        """根据 provider 解析 base_url，custom 优先使用自定义值"""
        if self.provider == "custom":
            return settings.CUSTOM_EMBEDDING_BASE_URL or self.provider_info["base_url"]
        if self.provider == "qwen":
            return settings.QWEN_BASE_URL or self.provider_info["base_url"]
        return self.provider_info["base_url"]

    def _resolve_api_key(self) -> str:
        """根据 provider 解析 api_key"""
        env_name = self.provider_info["api_key_env"]
        # 直接读环境变量，再 fallback 到 settings 中的值
        return os.getenv(env_name, "") or getattr(settings, env_name, "")

    def _resolve_group_id(self) -> str:
        """MiniMax 自研协议需要 GroupId（URL 查询参数）"""
        if self.protocol != "minimax":
            return ""
        env_name = self.provider_info.get("group_id_env", "MiniMax_GROUP_ID")
        return os.getenv(env_name, "") or getattr(settings, env_name, "")

    def encode(self, texts: List[str]) -> List[List[float]]:
        """编码入库向量（db 模式）"""
        return self._call_api(texts, emb_type="db")

    def encode_query(self, texts: List[str]) -> List[List[float]]:
        """编码查询向量（query 模式）
        对于 OpenAI 协议与 encode 相同；对于 MiniMax 协议会传 type='query'。
        """
        return self._call_api(texts, emb_type="query")

    def _call_api(self, texts: List[str], emb_type: str = "db") -> List[List[float]]:
        """统一 API 调用入口

        Args:
            texts: 输入文本列表
            emb_type: "db"（入库）或 "query"（检索）
        """
        # 降级：client 未初始化
        if self._client is None:
            return [LocalEmbedding._hash_embed(t, self._expected_dim) for t in texts]

        # MiniMax 自研协议（需 GroupId + 区分 db/query）
        if self.protocol == "minimax":
            return self._call_minimax(texts, emb_type)

        # OpenAI 兼容协议
        try:
            # 任务 P0: ModelScope API 强制要求 encoding_format（'float' 或 'base64'）
            # OpenAI 官方也接受，所以统一传
            response = self._client.embeddings.create(
                model=self.model, input=texts, encoding_format="float"
            )
            return [d.embedding for d in response.data]
        except Exception as e:
            self._handle_error(e, "OpenAI 协议")
            return [LocalEmbedding._hash_embed(t, self._expected_dim) for t in texts]

    def _call_minimax(self, texts: List[str], emb_type: str) -> List[List[float]]:
        """调用 MiniMax 自研 /v1/embeddings 协议

        请求格式：
            POST {base_url}/embeddings?GroupId={group_id}
            Authorization: Bearer <api_key>
            Body: {"texts": [...], "model": "embo-01", "type": "db" | "query"}

        返回：
            {"vectors": [[...], ...], "total_tokens": int, "base_resp": {...}}
        """
        if not self.group_id:
            print("[Embedding] MiniMax 缺少 GroupId，降级到 hash")
            return [LocalEmbedding._hash_embed(t, self._expected_dim) for t in texts]

        url = f"{self.base_url.rstrip('/')}/embeddings"
        params = {"GroupId": self.group_id}
        payload = {
            "texts": texts,
            "model": self.model,
            "type": emb_type,  # db=入库, query=检索
        }
        try:
            resp = self._session.post(url, params=params, json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()

            # 检查错误
            base_resp = data.get("base_resp", {})
            status_code = base_resp.get("status_code", 0)
            if status_code != 0:
                err_msg = base_resp.get("status_msg", "unknown error")
                raise RuntimeError(f"MiniMax 返回错误 {status_code}: {err_msg}")

            vectors = data.get("vectors", [])
            if not vectors:
                raise RuntimeError("MiniMax 返回的 vectors 为空")

            # MiniMax 返回的是 [[...]] 二维数组
            if isinstance(vectors[0], list):
                return vectors
            # 防御性：若返回一维，按单文本处理
            return [vectors]
        except Exception as e:
            self._handle_error(e, "MiniMax 协议")
            return [LocalEmbedding._hash_embed(t, self._expected_dim) for t in texts]

    def _handle_error(self, err: Exception, protocol_name: str):
        """统一错误处理"""
        print(f"[Embedding] {protocol_name} 调用失败: {err}")
        if settings.EMBEDDING_FALLBACK == "error":
            raise
        print("[Embedding] 降级到哈希伪向量")

    def dimension(self) -> int:
        return self._expected_dim

    def mode(self) -> str:
        return f"api_{self.provider}"

    def info(self) -> Dict[str, Any]:
        return {
            "mode": self.mode(),
            "dimension": self.dimension(),
            "model_name": self.model,
            "base_url": self.base_url,
            "provider": self.provider_info["label"],
            "protocol": self.protocol,
            "supports_embedding": self.provider_info["supports_embedding"],
            "has_api_key": bool(self.api_key),
            "group_id_configured": bool(self.group_id) if self.protocol == "minimax" else None,
            "note": self.provider_info["note"],
        }


class ModelScopeEmbedding(BaseEmbedding):
    """ModelScope 国内镜像嵌入"""

    def __init__(self):
        try:
            from modelscope.pipelines import pipeline
            from modelscope.utils.constant import Tasks
            self.pipeline = pipeline(
                Tasks.sentence_embedding,
                model='damo/nlp_corom_sentence-embedding_chinese-base'
            )
            self._dim = 768
        except ImportError:
            raise ImportError("请先安装 modelscope: pip install modelscope")

    def encode(self, texts: List[str]) -> List[List[float]]:
        result = self.pipeline(texts)
        return result['text_embedding'].tolist()

    def dimension(self) -> int:
        return self._dim

    def mode(self) -> str:
        return "modelscope"

    def info(self) -> Dict[str, Any]:
        return {
            "mode": self.mode(),
            "dimension": self.dimension(),
            "model_name": "damo/nlp_corom_sentence-embedding_chinese-base",
        }


# 全局嵌入实例
_embedding_service: BaseEmbedding = None


def get_embedding_service() -> BaseEmbedding:
    """获取嵌入服务（单例）"""
    global _embedding_service
    if _embedding_service is None:
        mode = settings.EMBEDDING_MODE
        if mode == "api":
            _embedding_service = APIEmbedding()
        elif mode == "modelscope":
            _embedding_service = ModelScopeEmbedding()
        else:  # local 或其他未知值
            _embedding_service = LocalEmbedding()

    return _embedding_service


def reset_embedding_service():
    """重置单例（用于切换 provider 后重新加载）"""
    global _embedding_service
    _embedding_service = None
    return get_embedding_service()

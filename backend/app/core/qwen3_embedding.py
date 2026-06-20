"""
任务 R：Qwen3-Embedding-0.6B 本地推理服务

特点：
- 1024 维输出（实际 Qwen3-Embedding-0.6B 模型维度）
- L2 归一化（直接支持余弦相似度 = 点积）
- CPU/GPU 自适应
- batch_size 默认 32（满足 ≥ 32 要求）
- max_length 8192（Qwen3-Embedding 标准输入长度）
- 支持中英文混合（多语言 Qwen3 tokenizer）

依赖：
- pip install torch transformers>=4.51.0 sentencepiece
"""
import os
import math
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_MODEL_NAME = "Qwen/Qwen3-Embedding-0.6B"
DEFAULT_DIM = 1024
DEFAULT_MAX_LENGTH = 8192
DEFAULT_BATCH_SIZE = 32


class Qwen3EmbeddingService:
    """Qwen3-Embedding 本地推理服务

    用法：
        svc = Qwen3EmbeddingService()
        vecs = svc.encode(["你好", "Hello"])
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        device: Optional[str] = None,
        max_length: int = DEFAULT_MAX_LENGTH,
        cache_dir: str = "models",
    ):
        self.model_name = model_name
        self.max_length = max_length
        self.cache_dir = cache_dir

        self._tokenizer = None
        self._model = None
        self._device = device or self._auto_device()
        self._dim: Optional[int] = None
        self._loaded = False

        self._load()

    def _auto_device(self) -> str:
        try:
            import torch
            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    def _load(self):
        """尝试加载模型；失败时记录详细错误"""
        try:
            import torch
            from transformers import AutoTokenizer, AutoModel

            logger.info(f"[Qwen3Embedding] 加载模型: {self.model_name} (device={self._device})")
            os.makedirs(self.cache_dir, exist_ok=True)

            self._tokenizer = AutoTokenizer.from_pretrained(
                self.model_name,
                cache_dir=self.cache_dir,
            )
            self._model = AutoModel.from_pretrained(
                self.model_name,
                cache_dir=self.cache_dir,
            )
            self._model.eval()
            self._model = self._model.to(self._device)

            self._dim = self._model.config.hidden_size
            self._loaded = True
            logger.info(
                f"[Qwen3Embedding] 加载成功: dim={self._dim}, "
                f"max_length={self.max_length}, device={self._device}"
            )
        except Exception as e:
            logger.error(
                f"[Qwen3Embedding] 加载失败: {type(e).__name__}: {e}\n"
                f"  解决：pip install torch transformers>=4.51.0 sentencepiece"
            )
            self._loaded = False

    def dimension(self) -> int:
        return self._dim or DEFAULT_DIM

    def is_loaded(self) -> bool:
        return self._loaded

    def encode(self, texts: List[str], batch_size: int = DEFAULT_BATCH_SIZE) -> List[List[float]]:
        """批量编码文本 → 1024 维 L2 归一化向量

        流程：
        1. 处理空字符串（Qwen3 tokenizer 不接受空串）
        2. tokenizer 编码（padding + truncation）
        3. 模型推理（last_hidden_state）
        4. Last-token pooling（Qwen3-Embedding 推荐方式）
        5. L2 归一化
        """
        if not texts:
            return []
        if not self._loaded or self._model is None:
            raise RuntimeError(
                "Qwen3-Embedding 模型未加载。请检查 torch/transformers 是否安装，"
                "或网络是否能下载模型权重。"
            )

        import torch
        # 过滤空串（Qwen3 tokenizer 不能处理空）
        safe_texts = [t if t and t.strip() else " " for t in texts]
        all_vecs: List[List[float]] = []

        with torch.no_grad():
            for i in range(0, len(safe_texts), batch_size):
                batch = safe_texts[i : i + batch_size]
                inputs = self._tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=self.max_length,
                    return_tensors="pt",
                )
                inputs = {k: v.to(self._device) for k, v in inputs.items()}
                outputs = self._model(**inputs)

                # Qwen3-Embedding 推荐 Last-Token Pooling
                # （取每个序列最后一个非 pad token 的隐藏状态）
                last_hidden = outputs.last_hidden_state  # (B, L, D)
                attention_mask = inputs["attention_mask"]  # (B, L)
                last_indices = attention_mask.sum(dim=1) - 1  # (B,)
                last_indices = last_indices.clamp(min=0)
                pooled = last_hidden[torch.arange(last_hidden.size(0), device=self._device), last_indices]

                # L2 归一化
                pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
                all_vecs.append(pooled.cpu().float().tolist())

        # flatten
        return [v for batch_vecs in all_vecs for v in batch_vecs]

    async def aencode(self, texts: List[str], batch_size: int = DEFAULT_BATCH_SIZE) -> List[List[float]]:
        """异步版本（CPU/GPU 推理仍同步，但接口 async 化便于调用方 await）"""
        # 推理在 GPU 仍是同步阻塞；放到线程池避免阻塞事件循环
        import asyncio
        return await asyncio.to_thread(self.encode, texts, batch_size)


# 单例（延迟加载）
_service_instance: Optional[Qwen3EmbeddingService] = None


def get_qwen3_embedding_service() -> Qwen3EmbeddingService:
    """获取全局单例（首次调用时加载模型）"""
    global _service_instance
    if _service_instance is None:
        model_name = os.getenv("QWEN3_EMBEDDING_MODEL", DEFAULT_MODEL_NAME)
        max_length = int(os.getenv("QWEN3_EMBEDDING_MAX_LENGTH", str(DEFAULT_MAX_LENGTH)))
        _service_instance = Qwen3EmbeddingService(
            model_name=model_name,
            max_length=max_length,
        )
    return _service_instance

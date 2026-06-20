"""
Embedding 管理 API

提供：
- GET  /api/embedding/info       当前 embedding 服务详情
- GET  /api/embedding/providers  支持的所有 provider
- POST /api/embedding/test       连通性测试
"""
import os
import time
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.config import settings, EMBEDDING_PROVIDERS
from app.core.embedding import (
    get_embedding_service, reset_embedding_service, APIEmbedding
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/info")
async def get_embedding_info():
    """获取当前 embedding 服务详情"""
    service = get_embedding_service()
    info = service.info()
    info["env"] = {
        "EMBEDDING_MODE": settings.EMBEDDING_MODE,
        "EMBEDDING_PROVIDER": settings.EMBEDDING_PROVIDER,
        "EMBEDDING_MODEL_OVERRIDE": settings.EMBEDDING_MODEL_OVERRIDE,
        "EMBEDDING_FALLBACK": settings.EMBEDDING_FALLBACK,
        "USE_REAL_EMBEDDING": os.getenv("USE_REAL_EMBEDDING", "0"),
        "EMBEDDING_MODEL_NAME": settings.EMBEDDING_MODEL_NAME,
    }
    return info


@router.get("/providers")
async def list_providers():
    """列出所有支持的 embedding provider 及其元数据"""
    return {
        "current_provider": settings.EMBEDDING_PROVIDER,
        "providers": [
            {
                "id": pid,
                **meta,
                "is_current": pid == settings.EMBEDDING_PROVIDER,
            }
            for pid, meta in EMBEDDING_PROVIDERS.items()
        ],
    }


class TestRequest(BaseModel):
    text: str = "你好世界，这是 embedding 连通性测试"
    provider: Optional[str] = None  # 临时指定 provider（不影响全局）
    api_key: Optional[str] = None  # 临时覆盖 api_key
    base_url: Optional[str] = None  # 临时覆盖 base_url
    model: Optional[str] = None  # 临时覆盖模型
    mode: str = "db"  # "db"（入库）或 "query"（检索）
    group_id: Optional[str] = None  # MiniMax 协议需要


@router.post("/test")
async def test_embedding(req: TestRequest):
    """连通性测试 - 实际调用一次 embedding API

    支持 db/query 双模式测试，可用于验证 MiniMax 协议是否正常工作。
    """
    start = time.time()
    test_text = req.text or "测试"

    try:
        if req.provider:
            # 临时构造 embedding 服务
            original_provider = settings.EMBEDDING_PROVIDER
            settings.EMBEDDING_PROVIDER = req.provider
            try:
                if req.api_key:
                    os.environ[EMBEDDING_PROVIDERS[req.provider]["api_key_env"]] = req.api_key
                if req.base_url:
                    os.environ.setdefault("CUSTOM_EMBEDDING_BASE_URL", req.base_url)
                if req.group_id:
                    os.environ["MiniMax_GROUP_ID"] = req.group_id
                test_service = APIEmbedding(provider=req.provider)
            finally:
                settings.EMBEDDING_PROVIDER = original_provider
        else:
            test_service = get_embedding_service()

        # 选择 encode 还是 encode_query
        if req.mode == "query":
            vec = test_service.encode_query([test_text])[0]
        else:
            vec = test_service.encode([test_text])[0]
        elapsed_ms = round((time.time() - start) * 1000, 2)

        return {
            "ok": True,
            "mode": test_service.mode(),
            "provider": getattr(test_service, "provider_info", {}).get("label", "local"),
            "protocol": getattr(test_service, "protocol", "openai"),
            "model": getattr(test_service, "model", "unknown"),
            "requested_mode": req.mode,
            "dimension": len(vec),
            "vector_norm": round(sum(x * x for x in vec) ** 0.5, 4),
            "vector_preview": vec[:5],
            "elapsed_ms": elapsed_ms,
            "text": test_text,
        }
    except Exception as e:
        elapsed_ms = round((time.time() - start) * 1000, 2)
        logger.error(f"[Embedding] 连通性测试失败: {e}")
        return {
            "ok": False,
            "error": str(e),
            "elapsed_ms": elapsed_ms,
            "text": test_text,
            "requested_mode": req.mode,
        }


class CompareRequest(BaseModel):
    """对比 db / query 模式的差异"""
    text: str = "什么是 RAG？"
    provider: Optional[str] = None


class EncodeRequest(BaseModel):
    texts: list[str]
    batch_size: Optional[int] = 32
    provider: Optional[str] = None  # 显式指定 provider（可选，默认走 settings）


class EncodeResponse(BaseModel):
    embeddings: list[list[float]]
    dim: int
    count: int
    time_ms: float
    model_name: str
    device: str
    provider: str


@router.post("/encode", response_model=EncodeResponse)
async def encode_texts(req: EncodeRequest):
    """任务 R：批量异步编码（支持 ≥ 32 条/batch）

    用法：
    curl -X POST http://localhost:8001/api/embedding/encode \\
      -H "Content-Type: application/json" \\
      -d '{"texts": ["你好", "Hello", ...]}'

    返回：每条文本的 L2 归一化向量（dim 取决于 provider）
    """
    if not req.texts:
        raise HTTPException(status_code=400, detail="texts 不能为空")
    if len(req.texts) > 1000:
        raise HTTPException(status_code=400, detail="单次最多 1000 条")
    if req.batch_size < 1 or req.batch_size > 256:
        raise HTTPException(status_code=400, detail="batch_size 必须在 1-256 之间")

    # 选择 provider
    if req.provider:
        # 临时构造指定 provider 的服务
        if req.provider == "qwen3_local":
            from app.core.qwen3_embedding import Qwen3EmbeddingService
            svc = Qwen3EmbeddingService()
            if not svc.is_loaded():
                raise HTTPException(status_code=503, detail="Qwen3-Embedding 模型未加载，请检查依赖（torch/transformers/sentencepiece）")
            t0 = time.time()
            try:
                vecs = svc.encode(req.texts, batch_size=req.batch_size)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"编码失败: {e}")
            return EncodeResponse(
                embeddings=vecs,
                dim=svc.dimension(),
                count=len(vecs),
                time_ms=(time.time() - t0) * 1000,
                model_name=svc.model_name,
                device=svc._device,
                provider="qwen3_local",
            )
        else:
            test_service = APIEmbedding(provider=req.provider)
    else:
        test_service = get_embedding_service()

    t0 = time.time()
    try:
        vecs = test_service.encode(req.texts)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"编码失败: {e}")

    info = test_service.info() if hasattr(test_service, "info") else {}
    return EncodeResponse(
        embeddings=vecs,
        dim=test_service.dimension(),
        count=len(vecs),
        time_ms=(time.time() - t0) * 1000,
        model_name=info.get("model_name", "?"),
        device=info.get("device", "?"),
        provider=req.provider or settings.EMBEDDING_PROVIDER,
    )


@router.post("/compare")
async def compare_db_query(req: CompareRequest):
    """对比 db 模式与 query 模式的差异（验证 MiniMax 双模式是否生效）"""
    if req.provider:
        test_service = APIEmbedding(provider=req.provider)
    else:
        test_service = get_embedding_service()

    try:
        vec_db = test_service.encode([req.text])[0]
        vec_query = test_service.encode_query([req.text])[0]
    except Exception as e:
        return {"ok": False, "error": str(e)}

    # 计算两者的余弦相似度
    from app.core.vector_store import _cosine_similarity
    sim = _cosine_similarity(vec_db, vec_query)

    return {
        "ok": True,
        "provider": getattr(test_service, "provider_info", {}).get("label", "local"),
        "protocol": getattr(test_service, "protocol", "openai"),
        "text": req.text,
        "db_mode": {
            "dimension": len(vec_db),
            "preview": vec_db[:3],
        },
        "query_mode": {
            "dimension": len(vec_query),
            "preview": vec_query[:3],
        },
        "db_query_similarity": round(sim, 4),
        "note": "若 db/query 模式完全相同（sim≈1.0），说明当前 provider 不区分两种模式；"
                "若 sim<0.99，说明 provider 使用了不同算法（这是 MiniMax 等厂商的优化）",
    }

"""
FastAPI 后端入口
"""
# 任务 P0: 兼容性补丁（必须最早导入！）
# 修复：huggingface_hub 0.16+ 移除了 is_offline_mode，但 transformers 旧版本还在引用
from app.core import compatibility  # noqa: F401  (必须先于 transformers 导入)

import logging
import warnings
from fastapi import FastAPI

# 过滤 numpy 警告
warnings.filterwarnings("ignore", category=RuntimeWarning, module="numpy")
from fastapi.middleware.cors import CORSMiddleware
# 性能优化：GZip 中间件（响应压缩，降低网络传输量）
from starlette.middleware.gzip import GZipMiddleware
# 性能优化：HTTP 缓存控制（Cache-Control 头）
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.api import router
from app.core.vector_store import VectorStore
from app.services.document_service import _documents, DocumentService
from app.core.chunking import ChunkingService


class CacheControlMiddleware(BaseHTTPMiddleware):
    """为静态可缓存接口设置 Cache-Control 头（性能优化）

    - /health、/api/embedding/info、/api/embedding/providers 等配置类接口：缓存 60s
    - /api/categories、/api/tags 等元数据接口：缓存 120s
    - 其他动态数据接口：不缓存
    """
    CACHEABLE = {
        "/health": 30,
        "/api/embedding/info": 60,
        "/api/embedding/providers": 60,
        "/api/categories": 120,
        "/api/tags": 60,
        "/api/vector/stats": 30,
    }

    async def dispatch(self, request, call_next):
        response: Response = await call_next(request)
        path = request.url.path
        if path in self.CACHEABLE and request.method == "GET":
            max_age = self.CACHEABLE[path]
            response.headers["Cache-Control"] = f"public, max-age={max_age}"
        return response

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("data/app.log", encoding="utf-8"),
    ],
)

app = FastAPI(
    title="知识库 API",
    description="基于 FastAPI + LangChain 的知识库后端服务",
    version="2.0.0"
)

# CORS 配置（生产环境可配置：ALLOWED_ORIGINS="https://kb.example.com,https://www.example.com"）
import os
_allowed_origins = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173"
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _allowed_origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 性能优化：GZip 中间件（>=500B 的响应自动压缩，降低网络传输量）
app.add_middleware(GZipMiddleware, minimum_size=500)

# 性能优化：Cache-Control 头（让浏览器/CDN 缓存可缓存接口）
app.add_middleware(CacheControlMiddleware)

# 注册路由
app.include_router(router, prefix="/api")


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.on_event("startup")
async def startup_event():
    """启动时检查并同步向量库

    任务：启动同步逻辑修复
    - 原 bug：仅当 existing_chunks == 0 时才重建。如果 vector_store.json 有旧数据
      （如 1 个文档的 33 chunks），则永远不重建 → 18 文档完全丢失。
    - 修复：基于"覆盖文档数 vs documents.json 文档数"判断
      - 若 doc_count > covered_docs + 容忍阈值 → 触发增量重建
      - 也支持环境变量 SKIP_STARTUP_REINDEX=1 跳过（紧急恢复用）
      - 也支持环境变量 FORCE_FULL_REINDEX=1 强制全量清空重建
    """
    import os
    # 紧急跳过开关
    if os.getenv("SKIP_STARTUP_REINDEX", "0") == "1":
        print("[STARTUP] SKIP_STARTUP_REINDEX=1, 跳过启动索引重建")
        return
    # 任务 Z：先尝试从 vector_store.json 自动迁移到 Chroma（一次性、幂等）
    try:
        from app.core.vector_store import migrate_json_to_chroma
        if migrate_json_to_chroma():
            print("[STARTUP] Chroma 数据迁移完成")
    except Exception as e:
        print(f"[STARTUP] Chroma 数据迁移失败（可忽略）: {e}")
    try:
        stats = VectorStore.get_stats()
        existing_chunks = stats.get("total_chunks", 0)
        covered_docs = stats.get("covered_docs", 0)
        total_docs_in_db = len(_documents)

        # 强制全量重建
        if os.getenv("FORCE_FULL_REINDEX", "0") == "1":
            print("[STARTUP] FORCE_FULL_REINDEX=1, 清空旧索引后全量重建...")
            _force_clear_index()
            existing_chunks = 0
            covered_docs = 0

        # 检查是否需要重建（基于文档覆盖率）
        missing_docs = total_docs_in_db - covered_docs
        need_reindex = (
            (total_docs_in_db > 0 and existing_chunks == 0) or
            (missing_docs > 0)  # 任何文档缺失都触发增量重建
        )

        if need_reindex:
            if existing_chunks == 0:
                print(f"[STARTUP] 检测到 {total_docs_in_db} 个文档但向量库为空，正在全量重建索引...")
            else:
                print(f"[STARTUP] 检测到 {total_docs_in_db} 个文档，仅 {covered_docs} 个已索引，{missing_docs} 个缺失，正在增量重建...")

            # 收集已索引的 doc_id，避免重复添加
            already_indexed = _get_indexed_doc_ids()

            doc_service = DocumentService()
            success_count = 0
            fail_count = 0
            new_chunks = 0
            for doc_id, doc in _documents.items():
                # 增量：跳过已索引的
                if doc_id in already_indexed:
                    continue
                try:
                    content = doc.content or ""
                    if not content.strip():
                        print(f"  [SKIP] {doc.title[:30]} (空内容)")
                        continue

                    # 使用递归分块作为默认策略
                    chunks = ChunkingService.chunk_text(
                        content,
                        strategy="recursive"
                    )

                    if chunks:
                        metadata = [{
                            "doc_id": doc.id,
                            "title": doc.title,
                            "category": getattr(doc, "category", "默认"),
                            "chunk_index": i,
                            "strategy": "recursive",
                            "rebuilt": True
                        } for i in range(len(chunks))]

                        VectorStore.add_document(doc.id, chunks, metadata)
                        new_chunks += len(chunks)
                        success_count += 1
                        print(f"  [OK] {doc.title[:30]:30s} | {len(chunks):3d} chunks | 总计 {existing_chunks + new_chunks}")
                    else:
                        print(f"  [SKIP] {doc.title[:30]} (分块为空)")

                except Exception as e:
                    fail_count += 1
                    print(f"  [FAIL] {doc.title[:30]} -> {e}")

            final_stats = VectorStore.get_stats()
            print(f"[STARTUP] 向量库重建完成 | 新增 {success_count} 文档 / 失败 {fail_count} / 新增 {new_chunks} chunks | 当前共 {final_stats.get('total_chunks', 0)} chunks / {final_stats.get('covered_docs', 0)} 文档")
        else:
            print(f"[STARTUP] 启动检查完成：{total_docs_in_db} 个文档，{covered_docs} 个已索引 ({existing_chunks} 个分块)")

    except Exception as e:
        import traceback
        print(f"[STARTUP] 启动时向量库同步失败: {e}")
        traceback.print_exc()


def _force_clear_index():
    """强制清空向量库（用于 FORCE_FULL_REINDEX，Chroma 兼容）"""
    import app.core.vector_store as vs_mod
    col = vs_mod._init_chroma()
    if col is not None:
        try:
            existing = col.get(include=[])
            if existing["ids"]:
                col.delete(ids=existing["ids"])
        except Exception as e:
            print(f"[_force_clear_index] Chroma 清空失败: {e}")
    else:
        # 兜底：清空 legacy JSON
        vs_mod._legacy_data["chunks"].clear()
        vs_mod._legacy_data["embeddings"].clear()
        vs_mod._legacy_data["metadata"].clear()
        vs_mod._legacy_data["ids"].clear()
        vs_mod._save_legacy()


def _get_indexed_doc_ids():
    """获取已索引的 doc_id 集合（用于增量重建，Chroma 兼容）"""
    import app.core.vector_store as vs_mod
    indexed = set()
    col = vs_mod._init_chroma()
    if col is not None:
        try:
            res = col.get(include=["metadatas"])
            for m in res.get("metadatas", []):
                if isinstance(m, dict):
                    did = m.get("doc_id")
                    if did:
                        indexed.add(did)
        except Exception as e:
            print(f"[_get_indexed_doc_ids] Chroma 读取失败: {e}")
    else:
        # 兜底：legacy JSON
        vs_mod._load_legacy()
        for m in vs_mod._legacy_data["metadata"]:
            if isinstance(m, dict):
                did = m.get("doc_id")
                if did:
                    indexed.add(did)
    return indexed

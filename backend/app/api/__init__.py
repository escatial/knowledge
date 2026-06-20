from fastapi import APIRouter

from .documents import router as documents_router
from .search import router as search_router
from .graph import router as graph_router
from .ai import router as ai_router
from .categories import router as categories_router
from .embedding import router as embedding_router
from .recycle import router as recycle_router
from .chunks import router as chunks_router
from .knowledge_bases import router as kb_router
# 任务 P0-3：版本 API
from .versions import router as versions_router
# 任务 P1-2：标签 API
from .tags import router as tags_router
# 任务 P2-2：参考文献 API
from .references import router as references_router

router = APIRouter()

router.include_router(versions_router, tags=["versions"])
router.include_router(tags_router, tags=["tags"])
router.include_router(references_router, tags=["references"])
router.include_router(documents_router, prefix="/documents", tags=["documents"])
router.include_router(search_router, prefix="/search", tags=["search"])
router.include_router(graph_router, prefix="/graph", tags=["graph"])
router.include_router(ai_router, prefix="/ai", tags=["ai"])
router.include_router(categories_router, prefix="/categories", tags=["categories"])
router.include_router(embedding_router, prefix="/embedding", tags=["embedding"])
router.include_router(recycle_router, prefix="/recycle", tags=["recycle"])
router.include_router(chunks_router, prefix="/chunks", tags=["chunks"])
router.include_router(kb_router, tags=["knowledge-bases"])

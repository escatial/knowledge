"""
分类管理 API - 支持动态扩展
"""
from typing import List
from fastapi import APIRouter

from app.core.chunking import ChunkingService, ChunkConfig
from app.services.document_service import _documents

router = APIRouter()


@router.get("/")
async def get_categories():
    """获取所有分类（已配置分类 + 文档中实际使用的分类）"""
    categories = []
    seen = set()

    # 1. 已配置的分类（CATEGORY_CONFIGS 中的，含分块策略）
    for name, config in ChunkingService.CATEGORY_CONFIGS.items():
        seen.add(name)
        categories.append({
            "name": name,
            "strategy": config.strategy,
            "chunk_size": config.chunk_size,
            "overlap": config.overlap
        })

    # 2. 文档中实际存在但尚未配置的分类（自动推断，使用默认策略）
    default_config = ChunkingService.CATEGORY_CONFIGS.get("默认", ChunkConfig(strategy="recursive", chunk_size=500, overlap=100))
    for doc in _documents.values():
        cat = doc.category
        if cat and cat not in seen:
            seen.add(cat)
            categories.append({
                "name": cat,
                "strategy": default_config.strategy,
                "chunk_size": default_config.chunk_size,
                "overlap": default_config.overlap
            })

    return categories


@router.post("/")
async def create_category(name: str, strategy: str = "recursive", chunk_size: int = 500, overlap: int = 100):
    """创建新分类"""
    if name in ChunkingService.CATEGORY_CONFIGS:
        return {"error": "分类已存在"}
    
    config = ChunkConfig(strategy=strategy, chunk_size=chunk_size, overlap=overlap)
    ChunkingService.add_category(name, config)
    return {"message": "分类创建成功", "name": name}


@router.put("/{name}")
async def update_category(name: str, strategy: str = "recursive", chunk_size: int = 500, overlap: int = 100):
    """更新分类配置"""
    if name not in ChunkingService.CATEGORY_CONFIGS:
        return {"error": "分类不存在"}
    
    config = ChunkConfig(strategy=strategy, chunk_size=chunk_size, overlap=overlap)
    ChunkingService.add_category(name, config) # 覆盖现有配置
    return {"message": "分类更新成功", "name": name}


@router.delete("/{name}")
async def delete_category(name: str):
    """删除分类"""
    if name == "默认":
        return {"error": "默认分类不能删除"}
    
    if name in ChunkingService.CATEGORY_CONFIGS:
        del ChunkingService.CATEGORY_CONFIGS[name]
        from app.core.chunking import _save_categories
        _save_categories()
        return {"message": "分类删除成功"}
    
    return {"error": "分类不存在"}


@router.post("/recommend")
async def recommend_chunking(text: str, title: str = ""):
    """推荐分块策略"""
    return ChunkingService.recommend_strategy(text, title)

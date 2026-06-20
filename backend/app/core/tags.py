"""任务 P1-2：多维度标签系统

设计：
- 独立标签表：data/tags.json
  结构：{ "tag_name": { "name", "category", "color", "doc_count", "created_at" } }
- 文档-标签关联：documents.json 中 doc 包含 tags: ["label1", "label2"]
- 标签维度分类：topic（主题）/ type（类型）/ level（难度）/ custom（自定义）
- 提供：增删改查、标签云统计、按标签过滤文档
"""
import json
import time
import threading
import logging
from pathlib import Path
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
TAGS_FILE = DATA_DIR / "tags.json"
_lock = threading.RLock()


# 预置标签维度分类
TAG_CATEGORIES = {
    "topic":   {"label": "主题",   "color": "blue",   "description": "技术主题 / 业务领域"},
    "type":    {"label": "类型",   "color": "green",  "description": "文档类型（教程/手册/规范/参考）"},
    "level":   {"label": "难度",   "color": "amber",  "description": "入门/进阶/专家"},
    "language":{"label": "语言",   "color": "purple", "description": "中文/英文/双语"},
    "custom":  {"label": "自定义", "color": "gray",   "description": "用户自定义标签"},
}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _load_tags() -> Dict[str, Dict[str, Any]]:
    if not TAGS_FILE.exists():
        return {}
    try:
        with open(TAGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.error(f"[_load_tags] failed: {e}")
        return {}


def _save_tags(tags: Dict[str, Dict[str, Any]]) -> None:
    with _lock:
        with open(TAGS_FILE, "w", encoding="utf-8") as f:
            json.dump(tags, f, ensure_ascii=False, indent=2)


def _normalize(name: str) -> str:
    """标签名归一化（小写 + 去空格）"""
    return name.strip().lower()


# =================== 标签管理 ===================
def create_tag(name: str, category: str = "custom", color: str = "",
               description: str = "") -> Dict[str, Any]:
    """创建标签"""
    name = _normalize(name)
    if not name:
        raise ValueError("标签名不能为空")
    if category not in TAG_CATEGORIES:
        category = "custom"
    tags = _load_tags()
    if name in tags:
        return tags[name]
    tag_obj = {
        "name": name,
        "display_name": name,
        "category": category,
        "color": color or TAG_CATEGORIES[category]["color"],
        "description": description,
        "doc_count": 0,
        "created_at": _now_iso(),
    }
    tags[name] = tag_obj
    _save_tags(tags)
    return tag_obj


def get_tag(name: str) -> Optional[Dict[str, Any]]:
    return _load_tags().get(_normalize(name))


def list_tags(category: Optional[str] = None) -> List[Dict[str, Any]]:
    """列出所有标签"""
    tags = _load_tags()
    out = list(tags.values())
    if category:
        out = [t for t in out if t.get("category") == category]
    # 按 doc_count 降序
    out.sort(key=lambda t: (-t.get("doc_count", 0), t.get("name", "")))
    return out


def delete_tag(name: str) -> bool:
    """删除标签（不影响文档中已存在的 tag 字符串，仅从标签表移除）"""
    name = _normalize(name)
    tags = _load_tags()
    if name not in tags:
        return False
    del tags[name]
    _save_tags(tags)
    return True


def increment_tag_count(name: str, delta: int = 1) -> None:
    """更新标签的 doc_count（文档添加/删除标签时调用）"""
    name = _normalize(name)
    tags = _load_tags()
    if name in tags:
        tags[name]["doc_count"] = max(0, tags[name].get("doc_count", 0) + delta)
        _save_tags(tags)


def sync_tag_counts(doc_tag_lists: List[List[str]]) -> None:
    """根据当前所有文档的 tag 列表重算 doc_count（一次性同步）"""
    counts: Dict[str, int] = {}
    for tag_list in doc_tag_lists:
        for t in (tag_list or []):
            t = _normalize(t)
            if t:
                counts[t] = counts.get(t, 0) + 1
    tags = _load_tags()
    for name, tag in tags.items():
        tag["doc_count"] = counts.get(name, 0)
    _save_tags(tags)


def list_tag_categories() -> List[Dict[str, str]]:
    return [
        {"name": k, **v}
        for k, v in TAG_CATEGORIES.items()
    ]

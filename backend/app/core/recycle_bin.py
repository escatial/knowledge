"""
回收站管理 - 文档级软删除 + 7 天自动清理

解决问题：
- 硬删除文档会导致知识图谱中"残留脏数据"和文档内容丢失
- 用户误删后可 7 天内恢复
- 恢复时自动重建图谱关联
"""
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional
from threading import Lock

from app.core.config import settings

logger = logging.getLogger(__name__)

RECYCLE_FILE = Path(settings.GRAPH_DATA_DIR) / "recycle_bin.json"
RETENTION_SECONDS = 7 * 24 * 3600  # 7 天


class RecycleBin:
    """文档回收站：单例，文件持久化"""

    def __init__(self):
        self._lock = Lock()
        self._items: Dict[str, dict] = {}  # doc_id -> {deleted_at, doc_data, content, graph_snapshot}
        self._load()

    def _load(self):
        try:
            if RECYCLE_FILE.exists():
                with open(RECYCLE_FILE, "r", encoding="utf-8") as f:
                    self._items = json.load(f)
                logger.info(f"[RecycleBin] 加载 {len(self._items)} 项")
        except Exception as e:
            logger.warning(f"[RecycleBin] 加载失败: {e}")
            self._items = {}

    def _save(self):
        try:
            RECYCLE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(RECYCLE_FILE, "w", encoding="utf-8") as f:
                json.dump(self._items, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[RecycleBin] 保存失败: {e}")

    def put(
        self,
        doc_id: str,
        doc_data: dict,
        content: str = "",
        graph_snapshot: Optional[dict] = None,
    ) -> dict:
        """放入回收站"""
        with self._lock:
            item = {
                "doc_id": doc_id,
                "doc_data": doc_data,
                "content": content[:10000] if content else "",  # 限 10K 防止爆炸
                "graph_snapshot": graph_snapshot or {},
                "deleted_at": time.time(),
                "expires_at": time.time() + RETENTION_SECONDS,
            }
            self._items[doc_id] = item
            self._save()
            return item

    def list(self, include_expired: bool = False) -> List[dict]:
        """列出所有未过期项"""
        now = time.time()
        with self._lock:
            items = list(self._items.values())
        if not include_expired:
            items = [it for it in items if it["expires_at"] > now]
        return sorted(items, key=lambda x: x["deleted_at"], reverse=True)

    def get(self, doc_id: str) -> Optional[dict]:
        return self._items.get(doc_id)

    def pop(self, doc_id: str) -> Optional[dict]:
        """从回收站取出（恢复时用）"""
        with self._lock:
            item = self._items.pop(doc_id, None)
            self._save()
            return item

    def cleanup_expired(self) -> int:
        """清理过期项，返回清理数量"""
        now = time.time()
        with self._lock:
            expired = [k for k, v in self._items.items() if v["expires_at"] < now]
            for k in expired:
                del self._items[k]
            self._save()
            if expired:
                logger.info(f"[RecycleBin] 清理 {len(expired)} 个过期项")
            return len(expired)


_recycle_bin = RecycleBin()


def get_recycle_bin() -> RecycleBin:
    return _recycle_bin

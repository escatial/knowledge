"""
任务优化：Query 级别 LRU 缓存层

解决的问题：
- 重复 query 重复调 LLM → 浪费 token + 延迟
- embedding 重复 encode → 浪费时间
- 用户体验：相同问题应秒回

实现：
- LRU 缓存 key = hash(query + history_summary)
- TTL = 5 分钟
- 容量 = 100 条
- 命中时跳过 embedding + LLM，直接返回
"""
import hashlib
import time
import threading
from collections import OrderedDict
from typing import Optional, Any, Dict


class QueryCache:
    """Query 级别 LRU 缓存

    Args:
        max_size: 最大缓存条数（默认 100）
        ttl_sec: 过期时间（默认 300s = 5 分钟）
    """

    def __init__(self, max_size: int = 100, ttl_sec: int = 300):
        self._cache: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_sec
        self._lock = threading.RLock()
        # 统计
        self._hits = 0
        self._misses = 0

    @staticmethod
    def make_key(query: str, knowledge_base_id: str = "all", extra: Optional[Dict] = None) -> str:
        """生成缓存 key

        Args:
            query: 用户问题
            knowledge_base_id: 知识库 ID（隔离不同 KB 的缓存）
            extra: 额外参数（如 session_id, history 摘要）
        """
        extra_str = ""
        if extra:
            for k in sorted(extra.keys()):
                extra_str += f"|{k}={extra[k]}"
        raw = f"{knowledge_base_id}::{query.strip()}::{extra_str}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """获取缓存值（命中返回 value，未命中或过期返回 None）"""
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None
            entry = self._cache[key]
            # 检查 TTL
            if time.time() - entry["ts"] > self._ttl:
                self._cache.pop(key)
                self._misses += 1
                return None
            # LRU：移动到末尾
            self._cache.move_to_end(key)
            self._hits += 1
            # 返回拷贝（避免外部修改污染缓存）
            return {
                "answer": entry["answer"],
                "citations": entry.get("citations", []),
                "intent": entry.get("intent"),
                "confidence": entry.get("confidence", 1.0),
                "cached_at": entry["ts"],
            }

    def set(self, key: str, value: Dict[str, Any]):
        """设置缓存值"""
        with self._lock:
            # 容量控制：超过 max_size 弹出最早的
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = {
                "answer": value.get("answer"),
                "citations": value.get("citations", []),
                "intent": value.get("intent"),
                "confidence": value.get("confidence", 1.0),
                "ts": time.time(),
            }
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def clear(self):
        """清空缓存"""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = self._hits / total if total > 0 else 0.0
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "ttl_sec": self._ttl,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(hit_rate, 4),
            }


# 全局单例
_query_cache = QueryCache(max_size=100, ttl_sec=300)


def get_query_cache() -> QueryCache:
    """获取全局 query 缓存实例"""
    return _query_cache

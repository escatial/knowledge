"""任务 T4：审计日志服务

设计：
- 存储：data/audit.log（JSON Lines 格式，每行一条）
- 记录：操作者 / 时间 / IP / 动作 / 资源 / 结果 / 详情
- 提供：写入 / 查询 / 导出
- 用途：安全审计、合规追溯、问题排查
"""
import json
import time
import logging
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
AUDIT_FILE = DATA_DIR / "audit.log"
_lock = threading.RLock()

# 动作枚举（便于检索与统计）
ACTIONS = {
    "LOGIN": "登录",
    "LOGOUT": "登出",
    "LOGIN_FAILED": "登录失败",
    "USER_CREATE": "创建用户",
    "USER_UPDATE": "修改用户",
    "USER_DEACTIVATE": "停用用户",
    "DOC_UPLOAD": "上传文档",
    "DOC_DELETE": "删除文档",
    "DOC_UPDATE": "修改文档",
    "KB_CREATE": "创建知识库",
    "KB_DELETE": "删除知识库",
    "AI_ASK": "AI 问答",
    "TAG_CREATE": "创建标签",
    "TAG_DELETE": "删除标签",
    "REF_CREATE": "创建引用",
    "VERSION_ROLLBACK": "版本回滚",
    "PERMISSION_DENIED": "权限拒绝",
    "CONFIG_CHANGE": "配置变更",
}


def _now_ts() -> float:
    return time.time()


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _anonymize(value: Optional[str]) -> Optional[str]:
    """简单匿名化（IPv4 末段归零）"""
    if not value:
        return value
    parts = value.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return f"{parts[0]}.{parts[1]}.{parts[2]}.0"
    return value


def log_event(
    action: str,
    username: str = "",
    resource: str = "",
    result: str = "success",
    detail: str = "",
    ip: str = "",
    user_agent: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """记录一条审计日志"""
    record = {
        "ts": _now_ts(),
        "iso": _now_iso(),
        "action": action,
        "username": username,
        "resource": resource,
        "result": result,
        "detail": detail,
        "ip": _anonymize(ip),
        "user_agent": user_agent[:200] if user_agent else "",
    }
    if extra:
        # 过滤 None / 不可序列化对象
        record["extra"] = {k: str(v) if not isinstance(v, (str, int, float, bool, list, dict)) else v
                           for k, v in extra.items()}
    try:
        with _lock:
            with open(AUDIT_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.error(f"[audit.log_event] failed: {e}")


def query_logs(
    action: Optional[str] = None,
    username: Optional[str] = None,
    start_ts: Optional[float] = None,
    end_ts: Optional[float] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """查询审计日志（按时间倒序）"""
    if not AUDIT_FILE.exists():
        return []
    out: List[Dict[str, Any]] = []
    try:
        with open(AUDIT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if action and rec.get("action") != action:
                    continue
                if username and rec.get("username") != username:
                    continue
                if start_ts and rec.get("ts", 0) < start_ts:
                    continue
                if end_ts and rec.get("ts", 0) > end_ts:
                    continue
                out.append(rec)
    except Exception as e:
        logger.error(f"[audit.query_logs] failed: {e}")
    out.sort(key=lambda r: r.get("ts", 0), reverse=True)
    return out[:limit]


def get_stats() -> Dict[str, Any]:
    """审计日志统计"""
    logs = query_logs(limit=100000)
    by_action: Dict[str, int] = {}
    by_user: Dict[str, int] = {}
    denied_count = 0
    for log in logs:
        a = log.get("action", "")
        by_action[a] = by_action.get(a, 0) + 1
        u = log.get("username", "")
        if u:
            by_user[u] = by_user.get(u, 0) + 1
        if a == "PERMISSION_DENIED" or log.get("result") == "denied":
            denied_count += 1
    return {
        "total_events": len(logs),
        "denied_count": denied_count,
        "by_action": dict(sorted(by_action.items(), key=lambda x: -x[1])[:10]),
        "top_users": dict(sorted(by_user.items(), key=lambda x: -x[1])[:10]),
        "log_file": str(AUDIT_FILE),
    }

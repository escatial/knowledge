"""任务 P0-2：RBAC 权限模型

设计：
- 权限点（Permission）：细粒度的能力标识（string: "doc:read"）
- 角色（Role）：一组权限点的集合（admin / editor / viewer）
- 用户（User）：拥有 1+ 个角色，权限为所有角色权限的并集

权限点命名规范：<resource>:<action>
- resource: doc / kb / ai / graph / chunk / user / settings
- action: read / write / delete
"""
import logging
from typing import Set, Dict, List

logger = logging.getLogger(__name__)


# =================== 权限点定义 ===================
PERMISSIONS: Dict[str, str] = {
    # 文档
    "doc:read":    "查看文档",
    "doc:write":   "上传/编辑文档",
    "doc:delete":  "删除文档",
    # 知识库
    "kb:read":     "查看知识库",
    "kb:write":    "创建/编辑知识库",
    "kb:delete":   "删除知识库",
    # AI 问答
    "ai:ask":      "AI 问答（同步）",
    "ai:stream":   "AI 流式问答",
    # 知识图谱
    "graph:read":  "查看图谱",
    "graph:write": "编辑图谱",
    # 向量分块
    "chunk:read":  "查看分块",
    "chunk:write": "编辑分块",
    # 用户管理
    "user:read":   "查看用户",
    "user:write":  "管理用户（创建/修改/停用）",
    # 系统设置
    "settings:read":  "查看设置",
    "settings:write": "修改设置",
}


# =================== 角色-权限映射 ===================
ROLE_PERMISSIONS: Dict[str, List[str]] = {
    # 管理员：全部权限
    "admin": list(PERMISSIONS.keys()),
    # 编辑者：内容相关（不含用户管理、不含系统设置修改）
    "editor": [
        "doc:read", "doc:write",
        "kb:read", "kb:write",
        "ai:ask", "ai:stream",
        "graph:read", "graph:write",
        "chunk:read", "chunk:write",
        "settings:read",
    ],
    # 访客：只读 + AI 问答
    "viewer": [
        "doc:read",
        "kb:read",
        "ai:ask", "ai:stream",
        "graph:read",
        "chunk:read",
        "settings:read",
    ],
}


# 角色展示信息
ROLE_INFO: Dict[str, Dict[str, str]] = {
    "admin":  {"label": "管理员", "color": "red",    "description": "全部权限"},
    "editor": {"label": "编辑者", "color": "blue",   "description": "内容管理"},
    "viewer": {"label": "访客",   "color": "gray",   "description": "只读 + AI"},
}


# =================== 权限查询 ===================
def get_role_permissions(role: str) -> Set[str]:
    """获取角色的所有权限"""
    return set(ROLE_PERMISSIONS.get(role, []))


def get_user_permissions(user: dict) -> Set[str]:
    """获取用户的所有权限（所有角色权限的并集）"""
    if not user:
        return set()
    roles = user.get("roles", [])
    perms: Set[str] = set()
    for role in roles:
        perms |= get_role_permissions(role)
    return perms


def user_has_permission(user: dict, perm: str) -> bool:
    """检查用户是否有指定权限"""
    if not user:
        return False
    if "admin" in user.get("roles", []):
        return True  # 超级权限短路
    return perm in get_user_permissions(user)


def user_has_any_permission(user: dict, perms: List[str]) -> bool:
    """检查用户是否有任意一个权限"""
    if not user:
        return False
    if "admin" in user.get("roles", []):
        return True
    user_perms = get_user_permissions(user)
    return any(p in user_perms for p in perms)


def list_all_roles() -> List[Dict[str, any]]:
    """列出所有角色（用于前端角色管理）"""
    return [
        {
            "name": name,
            "label": info["label"],
            "color": info["color"],
            "description": info["description"],
            "permissions": ROLE_PERMISSIONS.get(name, []),
        }
        for name, info in ROLE_INFO.items()
    ]

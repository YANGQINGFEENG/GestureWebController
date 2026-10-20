"""后台管理接口（M4-1）。

提供：
- GET    /api/admin/overview        四张表数量 + 全站手势分布 + 近 7 天趋势
- GET    /api/admin/users           用户列表（含每人三类记录条数，不含密码）
- PATCH  /api/admin/users/{uid}     改角色（user / admin）
- DELETE /api/admin/users/{uid}     删用户（记录随外键 CASCADE 一并删除）
- GET    /api/admin/records         全站手势记录
- GET    /api/admin/images          全站图片识别记录（带可直接 <img src> 的地址）
- GET    /api/admin/chats           全站问答记录（默认截断，后台表格不适合塞长文）

权限：整个路由挂 `require_db`，每个端点声明 `AdminUser`；非管理员是 403 而不是 404，
因为"接口存在但你没权限"对排障更有用（见 ADR-012）。
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.app.api.deps import AdminUser, DbSession, require_db
from backend.app.core.config import load_app_config
from backend.app.db import repository

router = APIRouter(
    prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_db)]
)


class RoleIn(BaseModel):
    role: Literal["user", "admin"]


def _image_url(rel_path: str) -> str | None:
    """相对路径 → 可直接访问的地址；落盘关闭时库里可能没有路径，返回 None。"""
    if not rel_path:
        return None
    if not load_app_config().upload.enabled:
        return None
    return f"/media/uploads/{rel_path}"


@router.get("/overview", summary="后台总览")
def overview(_: AdminUser, db: DbSession) -> dict:
    stats = repository.gesture_stats(db)
    return {
        "ok": True,
        "counts": repository.overview_stats(db),
        "gesture_stats": stats,
        # 后台首页把"覆盖手势数 / 平均置信度"也显示出来，这里直接从 stats 里取，
        # 避免前端自己算一遍导致和个人中心口径不一致
        "summary": {
            "gesture_kinds": len(stats["by_type"]),
            "avg_confidence": stats["avg_confidence"],
            "daily": stats["daily"],
        },
    }


@router.get("/users", summary="用户列表（含记录条数）")
def users(
    _: AdminUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    q: Annotated[str, Query(max_length=32, description="按账号或昵称搜索")] = "",
) -> dict:
    rows = repository.list_users(db, limit=limit, offset=offset, keyword=q.strip())
    counts = repository.count_records_by_uid(db)
    items = []
    for row in rows:
        item = row.to_public()
        item["counts"] = counts.get(row.uid, {"gesture": 0, "image": 0, "chat": 0})
        items.append(item)
    return {
        "ok": True,
        "total": repository.count_users(db, keyword=q.strip()),
        "limit": limit,
        "offset": offset,
        "items": items,
    }


@router.patch("/users/{uid}", summary="修改用户角色")
def patch_role(uid: int, payload: RoleIn, admin: AdminUser, db: DbSession) -> dict:
    target = repository.get_user(db, uid)
    if target is None:
        raise HTTPException(status_code=404, detail=f"用户 {uid} 不存在")
    if target.uid == admin.uid:
        raise HTTPException(status_code=422, detail="不能修改自己的角色，避免把后台锁死")
    if target.role == "admin" and payload.role != "admin" and repository.count_admins(db) <= 1:
        raise HTTPException(status_code=422, detail="至少要保留一个管理员")
    repository.set_user_role(db, target, payload.role)
    return {"ok": True, "user": target.to_public()}


@router.delete("/users/{uid}", summary="删除用户")
def remove_user(uid: int, admin: AdminUser, db: DbSession) -> dict:
    if uid == admin.uid:
        raise HTTPException(status_code=422, detail="不能删除自己")
    target = repository.get_user(db, uid)
    if target is None:
        raise HTTPException(status_code=404, detail=f"用户 {uid} 不存在")
    if target.role == "admin" and repository.count_admins(db) <= 1:
        raise HTTPException(status_code=422, detail="至少要保留一个管理员")
    repository.delete_user(db, target)
    return {"ok": True, "deleted": uid}


@router.get("/records", summary="全站手势记录")
def all_records(
    _: AdminUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    rows = repository.list_gesture_records(db, uid=None, limit=limit, offset=offset)
    return {
        "ok": True,
        "total": repository.count_gesture_records(db),
        "limit": limit,
        "offset": offset,
        "items": [row.to_dict() for row in rows],
    }


@router.get("/images", summary="全站图片识别记录")
def all_images(
    _: AdminUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    rows = repository.list_image_records(db, uid=None, limit=limit, offset=offset)
    items = []
    for row in rows:
        item = row.to_dict()
        # 前端不拼路径：静态目录随时可能换（本机 → 对象存储），地址由后端给
        item["img_url"] = _image_url(row.img_path)
        items.append(item)
    return {
        "ok": True,
        "total": repository.count_image_records(db),
        "limit": limit,
        "offset": offset,
        "items": items,
    }


@router.get("/chats", summary="全站问答记录")
def all_chats(
    _: AdminUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
    preview: Annotated[int, Query(ge=0, le=500, description="截断长度，0 表示不截断")] = 120,
) -> dict:
    rows = repository.list_chat_records(db, uid=None, limit=limit, offset=offset)
    return {
        "ok": True,
        "total": repository.count_chat_records(db),
        "limit": limit,
        "offset": offset,
        "items": [row.to_dict(preview=preview) for row in rows],
    }

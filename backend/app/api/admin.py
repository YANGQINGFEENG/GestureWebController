"""后台管理接口（最小集，M4 补全前端页面与更多操作）。

当前提供：
- GET /api/admin/overview   四张表数量 + 全站手势分布
- GET /api/admin/users      用户列表（不含密码）
- GET /api/admin/records    全站手势记录
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backend.app.api.deps import AdminUser, DbSession, require_db
from backend.app.db import repository

router = APIRouter(
    prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_db)]
)


@router.get("/overview", summary="后台总览")
def overview(_: AdminUser, db: DbSession) -> dict:
    return {
        "ok": True,
        "counts": repository.overview_stats(db),
        "gesture_stats": repository.gesture_stats(db),
    }


@router.get("/users", summary="用户列表")
def users(
    _: AdminUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    rows = repository.list_users(db, limit=limit, offset=offset)
    return {"ok": True, "items": [row.to_public() for row in rows]}


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
        "items": [row.to_dict() for row in rows],
    }

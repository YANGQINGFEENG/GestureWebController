"""记录接口：手势记录上报 / 列表 / 删除 / 统计。

核心设计（ADR-006 可插拔日志层）：
- 上报接口**先保证不阻断操控**：数据库异常或记录功能关闭时仍返回 2xx，只是 `saved=false`
  并给出 reason，前端拿到后忽略即可，绝不因为"日志没写进去"影响翻页；
- 未登录也允许上报（uid 记 null），这样别人把 SDK 嵌到自己页面上试用不要求先注册；
- 手势的中文名与动作从 config/gesture_map.json 取，客户端只需传 gesture_type 与置信度，
  避免前端配置漂移导致库里出现"同一个手势两种名字"。
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError

from backend.app.api.deps import CurrentUser, DbSession, MaybeDb, OptionalUser, require_db
from backend.app.core.config import load_app_config, load_gesture_map
from backend.app.db import repository
from backend.app.db.session import db_unavailable_reason

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/records", tags=["records"])


class GestureReportIn(BaseModel):
    gesture_type: str = Field(..., description="手势语义 id，如 peace / point / palm")
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    action: str = Field("", max_length=32, description="留空则按 gesture_map 自动补")
    source: Literal["camera", "video", "images", "unknown"] = "camera"
    infer_ms: float = Field(0.0, ge=0.0, le=10000.0)


@router.post(
    "/gesture",
    summary="上报一次手势触发",
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"description": "已接收但未落库（数据库不可用或记录功能关闭），不影响操控"}
    },
)
def report_gesture(
    payload: GestureReportIn,
    user: OptionalUser,
    db: MaybeDb,
) -> dict:
    gesture = next(
        (g for g in load_gesture_map().gestures if g.id == payload.gesture_type), None
    )
    if gesture is None:
        known = ", ".join(g.id for g in load_gesture_map().gestures)
        raise HTTPException(
            status_code=422, detail=f"未知手势类型 {payload.gesture_type}；可用：{known}"
        )

    if db is None or not load_app_config().records.enabled:
        reason = "记录功能已在配置中关闭" if db is not None else (db_unavailable_reason() or "数据库不可用")
        return {"ok": True, "saved": False, "reason": reason, "record": None}

    try:
        record = repository.add_gesture_record(
            db,
            uid=user.uid if user else None,
            gesture_type=gesture.id,
            gesture_label=gesture.label,
            action=payload.action or gesture.action,
            confidence=payload.confidence,
            infer_ms=payload.infer_ms,
            source=payload.source,
        )
    except SQLAlchemyError as exc:
        # 写失败只记日志：手势操控是主功能，记录是附加能力
        logger.warning("手势记录落库失败（不影响操控）：%s", exc)
        db.rollback()
        return {"ok": True, "saved": False, "reason": "数据库写入失败", "record": None}

    return {"ok": True, "saved": True, "record": record.to_dict()}


@router.get("/gesture", summary="我的手势记录（分页）", dependencies=[Depends(require_db)])
def list_gestures(
    user: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    rows = repository.list_gesture_records(db, uid=user.uid, limit=limit, offset=offset)
    return {
        "ok": True,
        "total": repository.count_gesture_records(db, uid=user.uid),
        "limit": limit,
        "offset": offset,
        "items": [row.to_dict() for row in rows],
    }


@router.delete("/gesture/{record_id}", summary="删除一条手势记录")
def delete_gesture(record_id: int, user: CurrentUser, db: DbSession) -> dict:
    deleted = repository.delete_gesture_record(
        db, record_id=record_id, uid=user.uid, is_admin=user.is_admin
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="记录不存在或无权删除")
    return {"ok": True, "deleted": record_id}


@router.get("/gesture/stats", summary="我的手势统计")
def gesture_stats(user: CurrentUser, db: DbSession) -> dict:
    return {"ok": True, "stats": repository.gesture_stats(db, uid=user.uid)}


@router.get("/image", summary="我的图片识别记录", dependencies=[Depends(require_db)])
def list_images(
    user: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    rows = repository.list_image_records(db, uid=user.uid, limit=limit, offset=offset)
    return {
        "ok": True,
        "total": repository.count_image_records(db, uid=user.uid),
        "limit": limit,
        "offset": offset,
        "items": [row.to_dict() for row in rows],
    }


@router.get("/chat", summary="我的问答记录", dependencies=[Depends(require_db)])
def list_chats(
    user: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    rows = repository.list_chat_records(db, uid=user.uid, limit=limit, offset=offset)
    return {
        "ok": True,
        "total": repository.count_chat_records(db, uid=user.uid),
        "limit": limit,
        "offset": offset,
        "items": [row.to_dict() for row in rows],
    }

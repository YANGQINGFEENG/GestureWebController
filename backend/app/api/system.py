"""系统状态接口：给演示页和运维用的自检入口。

与 /api/health 的分工：
- /api/health（predict.py）：只管模型能不能推理，不依赖数据库；
- /api/system/status（本文件）：数据库、鉴权、记录开关等运行环境信息。
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.core.config import load_app_config, load_gesture_map
from backend.app.core.security import peek_secret_source
from backend.app.db import repository
from backend.app.db.session import SessionLocal, db_available, db_unavailable_reason

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/status", summary="运行环境自检")
def status() -> dict:
    cfg = load_app_config()
    available = db_available()

    counts: dict[str, int] | None = None
    if available:
        session = SessionLocal()
        try:
            counts = repository.overview_stats(session)
        except Exception:  # noqa: BLE001 - 统计失败不该让状态接口 500
            counts = None
        finally:
            session.close()

    return {
        "ok": True,
        "database": {
            "driver": cfg.database.url.split(":", 1)[0],
            "enabled": cfg.database.enabled,
            "available": available,
            "reason": None if available else (db_unavailable_reason() or "未初始化"),
            "counts": counts,
        },
        "records": {"enabled": cfg.records.enabled},
        "auth": {
            "allow_register": cfg.auth.allow_register,
            "token_ttl_hours": cfg.auth.expire_hours,
            "secret_source": peek_secret_source(),
        },
        "gestures": [g.id for g in load_gesture_map().gestures],
    }

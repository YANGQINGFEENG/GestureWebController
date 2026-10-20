"""数据库初始化与种子数据。

种子策略：
- 库为空时自动创建管理员账号，账号密码优先取环境变量 GWC_ADMIN_USER / GWC_ADMIN_PASSWORD，
  未设置则用 admin / admin123456 并在日志里显式警告（仅课程演示，生产必须改）。
- 已有任何用户时不做任何写入，避免覆盖真实数据。
"""

from __future__ import annotations

import logging
import os

from backend.app.core.security import hash_password
from backend.app.db import repository
from backend.app.db.models import User
from backend.app.db.session import SessionLocal, db_available

logger = logging.getLogger(__name__)

DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123456"


def ensure_admin() -> None:
    if not db_available():
        return

    session = SessionLocal()
    try:
        if session.query(User).count() > 0:
            return
        username = os.getenv("GWC_ADMIN_USER", DEFAULT_ADMIN_USER)
        password = os.getenv("GWC_ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)
        repository.create_user(
            session,
            username=username,
            password_hash=hash_password(password),
            nickname="管理员",
            role="admin",
        )
        if password == DEFAULT_ADMIN_PASSWORD:
            logger.warning(
                "已创建默认管理员 %s / %s —— 演示可用，上线前请设置 GWC_ADMIN_PASSWORD 修改",
                username,
                password,
            )
        else:
            logger.info("已创建管理员账号：%s", username)
    except Exception as exc:  # noqa: BLE001 - 种子失败不阻断服务启动
        logger.warning("创建管理员账号失败：%s", exc)
        session.rollback()
    finally:
        session.close()

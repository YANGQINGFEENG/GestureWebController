"""数据库连接与会话管理。

设计要点（ADR-011）：
- SQLite 单文件，零安装；启用 WAL 与外键约束，兼顾并发读与参照完整性。
- 引擎懒加载：数据库配置错误不应该让"手势识别"这个主功能起不来。
- `db_available()` 供 API 层判断是否降级；任何一次数据库异常都不向上抛到操控链路。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import Engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import load_app_config
from backend.app.db.models import Base

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_init_error: str | None = None


def _create_engine() -> Engine:
    from sqlalchemy import create_engine

    cfg = load_app_config().database
    if cfg.is_sqlite:
        # 相对路径已在 config 层转成绝对路径；此处只负责确保父目录存在
        db_path = Path(cfg.url.replace("sqlite:///", ""))
        db_path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            cfg.url,
            echo=cfg.echo,
            future=True,
            connect_args={"check_same_thread": False, "timeout": 10},
        )

        @event.listens_for(engine, "connect")
        def _sqlite_pragma(dbapi_connection, _record) -> None:  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")  # SQLite 默认不校验外键，必须显式打开
            cursor.execute("PRAGMA journal_mode=WAL")  # 读写不互斥，识别与写日志可并行
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

        return engine

    return create_engine(cfg.url, echo=cfg.echo, future=True, pool_pre_ping=True)


def get_engine() -> Engine:
    """首次调用时建引擎并建表；失败后不再重试，由 db_available() 返回 False。"""
    global _engine, _session_factory, _init_error
    if _engine is not None:
        return _engine

    with _lock:
        if _engine is not None:
            return _engine
        cfg = load_app_config()
        if not cfg.database.enabled:
            _init_error = "database.enabled = false"
            raise RuntimeError(_init_error)
        try:
            engine = _create_engine()
            if cfg.database.create_tables:
                Base.metadata.create_all(engine)
            _engine = engine
            _session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
            _init_error = None
            logger.info("数据库就绪：%s", cfg.database.url)
            return engine
        except Exception as exc:  # noqa: BLE001
            _init_error = str(exc)
            logger.warning("数据库不可用（手势操控不受影响，仅记录不落库）：%s", exc)
            raise RuntimeError(_init_error) from exc


def db_available() -> bool:
    """探测数据库是否可用；不可用只影响记录落库，不影响 /api/predict。"""
    try:
        engine = get_engine()
    except Exception:  # noqa: BLE001
        return False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("数据库探测失败：%s", exc)
        return False


def db_unavailable_reason() -> str | None:
    return _init_error


def SessionLocal() -> Session:
    if _session_factory is None:
        get_engine()
    if _session_factory is None:  # pragma: no cover - get_engine 已抛错
        raise RuntimeError("数据库未初始化")
    return _session_factory()


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：请求结束时自动关闭；异常时回滚。"""
    session = SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> bool:
    """启动时调用，返回是否可用（不抛异常）。"""
    try:
        get_engine()
        return True
    except Exception:  # noqa: BLE001
        return False


def dispose_engine() -> None:
    """测试用：释放连接并重置，便于切换数据库地址。"""
    global _engine, _session_factory, _init_error
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _session_factory = None
        _init_error = None

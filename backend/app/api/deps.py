"""FastAPI 依赖：从请求里解析当前用户。

三种粒度：
- `current_user`   必须登录，否则 401        （个人中心、记录列表）
- `optional_user`  可选登录，未登录返回 None （手势记录上报：未登录也允许，uid 记 null）
- `admin_user`     必须管理员，否则 403      （后台管理）

为什么不直接返回 ORM 的 User：依赖注入的 Session 与接口里的 Session 可能不是同一个
（上报接口要容忍数据库不可用，用的是另一个依赖），把 ORM 对象跨 Session 传递会触发
"object already attached to session"。这里只把需要的字段拷成 `AuthUser`，
接口要用完整用户信息时再用自己的 Session 重新查一次。
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.core.security import TokenError, decode_token
from backend.app.db import repository
from backend.app.db.models import User
from backend.app.db.session import SessionLocal, db_available, get_db

DbSession = Annotated[Session, Depends(get_db)]


def get_db_or_none() -> Iterator[Session | None]:
    """数据库不可用时也返回一个可用的依赖（值为 None）。

    存在的理由：手势上报接口不允许因为数据库挂掉而 500——它得始终回 2xx，
    只是 saved=false。其他业务接口用 `require_db` 明确报 503。
    """
    if not db_available():
        yield None
        return
    session = SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


MaybeDb = Annotated[Session | None, Depends(get_db_or_none)]


@dataclass(frozen=True)
class AuthUser:
    """登录用户的最小快照，脱离 ORM 会话生命周期。"""

    uid: int
    username: str
    nickname: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @classmethod
    def of(cls, user: User) -> "AuthUser":
        return cls(
            uid=user.uid,
            username=user.username,
            nickname=user.nickname or user.username,
            role=user.role,
        )

    def to_public(self) -> dict:
        return {
            "uid": self.uid,
            "username": self.username,
            "nickname": self.nickname,
            "role": self.role,
        }


def _extract_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def _resolve_user(db: Session | None, authorization: str | None) -> AuthUser | None:
    token = _extract_token(authorization)
    if token is None:
        return None
    try:
        payload = decode_token(token)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    if db is None:
        # 数据库不可用时无法核实账号是否存在，按游客处理，保证上报接口仍可用
        return None
    try:
        uid = int(payload.get("sub", 0))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="登录凭证无效") from exc
    user = repository.get_user(db, uid)
    if user is None:
        # token 有效但用户被删除：当作未登录处理，避免脏 token 长期可用
        raise HTTPException(status_code=401, detail="账号不存在，请重新登录")
    return AuthUser.of(user)


def optional_user(
    db: MaybeDb,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthUser | None:
    return _resolve_user(db, authorization)


def current_user(user: Annotated[AuthUser | None, Depends(optional_user)]) -> AuthUser:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def admin_user(user: Annotated[AuthUser, Depends(current_user)]) -> AuthUser:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


def require_db() -> None:
    """登录/记录类接口的前置检查：数据库不可用时给出明确提示而不是 500。"""
    if not db_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="数据库不可用，账号与记录功能暂不可用（手势识别不受影响）",
        )


CurrentUser = Annotated[AuthUser, Depends(current_user)]
OptionalUser = Annotated[AuthUser | None, Depends(optional_user)]
AdminUser = Annotated[AuthUser, Depends(admin_user)]

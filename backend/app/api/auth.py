"""账号接口：注册 / 登录 / 我的信息 / 修改信息。

安全约定：
- 密码只以 bcrypt 哈希入库，任何响应都不回传哈希；
- 登录失败统一返回"账号或密码错误"，不区分账号不存在与密码错误，避免账号枚举；
- 修改密码必须验证旧密码。
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from backend.app.api.deps import CurrentUser, DbSession, require_db
from backend.app.core.config import load_app_config
from backend.app.core.security import (
    create_access_token,
    hash_password,
    token_ttl_seconds,
    verify_password,
)
from backend.app.db import repository
from backend.app.db.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"], dependencies=[Depends(require_db)])

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")


class RegisterIn(BaseModel):
    username: str = Field(..., description="3~32 位字母/数字/下划线")
    password: str = Field(..., description="至少 6 位")
    nickname: str = Field("", max_length=32)

    @field_validator("username")
    @classmethod
    def _check_username(cls, value: str) -> str:
        value = value.strip()
        if not USERNAME_RE.match(value):
            raise ValueError("账号需为 3~32 位字母、数字或下划线")
        return value

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        minimum = load_app_config().auth.min_password_length
        if len(value) < minimum:
            raise ValueError(f"密码至少 {minimum} 位")
        if len(value) > 64:
            raise ValueError("密码过长（上限 64 位）")
        return value


class LoginIn(BaseModel):
    username: str
    password: str


class UpdateMeIn(BaseModel):
    nickname: str | None = Field(None, max_length=32)
    old_password: str | None = None
    new_password: str | None = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


def _issue(user: User) -> TokenOut:
    return TokenOut(
        access_token=create_access_token(user.uid, user.role),
        expires_in=token_ttl_seconds(),
        user=user.to_public(),
    )


@router.post("/register", summary="注册", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterIn, db: DbSession) -> TokenOut:
    if not load_app_config().auth.allow_register:
        raise HTTPException(status_code=403, detail="当前已关闭注册，请联系管理员开通账号")
    try:
        user = repository.create_user(
            db,
            username=payload.username,
            password_hash=hash_password(payload.password),
            nickname=payload.nickname.strip(),
            role="user",
        )
    except repository.DuplicateUsernameError as exc:
        raise HTTPException(status_code=409, detail="该账号已被注册") from exc
    return _issue(user)


@router.post("/login", summary="登录")
def login(payload: LoginIn, db: DbSession) -> TokenOut:
    user = repository.get_user_by_username(db, payload.username.strip())
    # 账号不存在时也走一次哈希校验，让两种失败的响应耗时接近，减少时序侧信道
    reference_hash = user.password_hash if user else "$2b$12$" + "x" * 53
    if not verify_password(payload.password, reference_hash) or user is None:
        raise HTTPException(status_code=401, detail="账号或密码错误")
    return _issue(user)


@router.get("/me", summary="我的信息")
def me(user: CurrentUser, db: DbSession) -> dict:
    row = repository.get_user(db, user.uid)
    if row is None:
        raise HTTPException(status_code=401, detail="账号不存在，请重新登录")
    return {"ok": True, "user": row.to_public()}


@router.patch("/me", summary="修改昵称 / 密码")
def update_me(payload: UpdateMeIn, user: CurrentUser, db: DbSession) -> dict:
    row = repository.get_user(db, user.uid)
    if row is None:
        raise HTTPException(status_code=401, detail="账号不存在，请重新登录")

    nickname = payload.nickname.strip() if payload.nickname is not None else None
    if nickname is not None and not nickname:
        raise HTTPException(status_code=422, detail="昵称不能为空")

    password_hash: str | None = None
    if payload.new_password:
        if not payload.old_password:
            raise HTTPException(status_code=422, detail="修改密码需要提供原密码")
        if not verify_password(payload.old_password, row.password_hash):
            raise HTTPException(status_code=400, detail="原密码不正确")
        minimum = load_app_config().auth.min_password_length
        if len(payload.new_password) < minimum:
            raise HTTPException(status_code=422, detail=f"新密码至少 {minimum} 位")
        password_hash = hash_password(payload.new_password)

    if nickname is None and password_hash is None:
        raise HTTPException(status_code=422, detail="没有需要修改的内容")

    updated = repository.update_user(db, row, nickname=nickname, password_hash=password_hash)
    return {"ok": True, "user": updated.to_public()}

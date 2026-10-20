"""认证基础件：密码哈希（bcrypt）与 JWT 签发/校验。

密钥策略（ADR-012）：
- 优先读环境变量 GWC_JWT_SECRET，其次 config/app.yaml 的 auth.secret；
- 两者都为空时，自动生成随机密钥写入 data/.jwt_secret（已被 .gitignore 排除），
  保证"克隆下来就能跑"，同时不会把密钥提交进仓库；
- 多机部署必须显式设置 GWC_JWT_SECRET，否则各机签发 token 互不认。
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import bcrypt
import jwt

from backend.app.core.config import ROOT, load_app_config

logger = logging.getLogger(__name__)

SECRET_FILE = ROOT / "data" / ".jwt_secret"
_BCRYPT_MAX_BYTES = 72  # bcrypt 算法上限，超出部分会被截断（新版库直接报错）
_secret_cache: str | None = None


def _load_secret() -> str:
    global _secret_cache
    if _secret_cache:
        return _secret_cache

    configured = load_app_config().auth.secret.strip()
    if configured:
        _secret_cache = configured
        return configured

    if SECRET_FILE.exists():
        existing = SECRET_FILE.read_text(encoding="utf-8").strip()
        if existing:
            _secret_cache = existing
            return existing

    generated = secrets.token_urlsafe(48)
    SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    SECRET_FILE.write_text(generated, encoding="utf-8")
    logger.warning("未配置 JWT 密钥，已生成随机密钥并写入 %s（请勿提交，生产环境请设 GWC_JWT_SECRET）", SECRET_FILE)
    _secret_cache = generated
    return generated


def hash_password(password: str) -> str:
    """bcrypt 哈希。同一密码每次结果不同（随机盐），只可校验不可逆推。"""
    raw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        raw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
        return bcrypt.checkpw(raw, password_hash.encode("ascii"))
    except (ValueError, TypeError):
        # 哈希格式损坏 / 空密码等情况一律视为校验失败，不抛异常给调用方
        return False


def create_access_token(uid: int, role: str, expire_hours: int | None = None) -> str:
    cfg = load_app_config().auth
    hours = int(expire_hours if expire_hours is not None else cfg.expire_hours)
    now = datetime.now(UTC)
    payload = {
        "sub": str(uid),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=hours)).timestamp()),
    }
    return jwt.encode(payload, _load_secret(), algorithm=cfg.algorithm)


class TokenError(Exception):
    """token 缺失、过期、签名不符。"""


def decode_token(token: str) -> dict[str, Any]:
    cfg = load_app_config().auth
    try:
        return jwt.decode(token, _load_secret(), algorithms=[cfg.algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("登录已过期，请重新登录") from exc
    except jwt.PyJWTError as exc:
        raise TokenError("登录凭证无效") from exc


def token_ttl_seconds() -> int:
    return load_app_config().auth.expire_hours * 3600


def peek_secret_source() -> str:
    """给 /api/health 用：说明密钥来自哪里，但不泄漏密钥本身。"""
    if load_app_config().auth.secret.strip():
        return "env-or-config"
    return "auto-generated" if Path(SECRET_FILE).exists() else "unknown"

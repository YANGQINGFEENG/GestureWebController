"""数据访问层：所有 SQL / ORM 查询集中在这里，API 层只调函数。

分层理由：M3 的图片识别、AI 问答都要写记录，如果让每个接口自己拿 Session 拼查询，
外键、分页、时区这些细节会各写一遍。集中之后，换数据库（SQLite → MySQL/Postgres）
只需要动 db/session.py。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.db.models import ChatRecord, GestureRecord, ImageRecord, User


class DuplicateUsernameError(Exception):
    """注册时用户名已存在。"""


# --------------------------------------------------------------------------- 用户


def get_user(db: Session, uid: int) -> User | None:
    return db.get(User, uid)


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username))


def create_user(
    db: Session,
    *,
    username: str,
    password_hash: str,
    nickname: str = "",
    role: str = "user",
) -> User:
    if get_user_by_username(db, username) is not None:
        raise DuplicateUsernameError(username)
    user = User(
        username=username,
        password_hash=password_hash,
        nickname=nickname or username,
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user(
    db: Session,
    user: User,
    *,
    nickname: str | None = None,
    password_hash: str | None = None,
) -> User:
    if nickname is not None:
        user.nickname = nickname
    if password_hash is not None:
        user.password_hash = password_hash
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def list_users(
    db: Session, limit: int = 50, offset: int = 0, *, keyword: str = ""
) -> list[User]:
    stmt = select(User).order_by(User.uid.desc()).limit(limit).offset(offset)
    if keyword:
        # 账号或昵称模糊匹配；SQLite 的 LIKE 对 ASCII 不区分大小写，中文按原样匹配
        like = f"%{keyword}%"
        stmt = stmt.where((User.username.like(like)) | (User.nickname.like(like)))
    return list(db.scalars(stmt))


def count_users(db: Session, *, keyword: str = "") -> int:
    stmt = select(func.count()).select_from(User)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where((User.username.like(like)) | (User.nickname.like(like)))
    return int(db.scalar(stmt) or 0)


def count_records_by_uid(db: Session) -> dict[int, dict[str, int]]:
    """每个用户三类记录的条数，后台用户表一次查完，避免 N+1。

    返回 {uid: {"gesture": n, "image": n, "chat": n}}；uid 为 null 的游客记录不在其中。
    """
    result: dict[int, dict[str, int]] = {}
    tables = (
        ("gesture", GestureRecord, GestureRecord.uid),
        ("image", ImageRecord, ImageRecord.uid),
        ("chat", ChatRecord, ChatRecord.uid),
    )
    for key, model, uid_col in tables:
        rows = db.execute(
            select(uid_col, func.count()).where(uid_col.is_not(None)).group_by(uid_col)
        ).all()
        for uid, count in rows:
            slot = result.setdefault(int(uid), {"gesture": 0, "image": 0, "chat": 0})
            slot[key] = int(count)
    return result


def set_user_role(db: Session, user: User, role: str) -> User:
    user.role = role
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user: User) -> None:
    """删除用户；SQLite 已开 PRAGMA foreign_keys=ON，记录随 CASCADE 一起删。"""
    db.delete(user)
    db.commit()


def count_admins(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(User).where(User.role == "admin")) or 0)


# --------------------------------------------------------------------------- 手势记录


def add_gesture_record(
    db: Session,
    *,
    uid: int | None,
    gesture_type: str,
    gesture_label: str = "",
    action: str = "",
    confidence: float = 0.0,
    infer_ms: float = 0.0,
    source: str = "camera",
) -> GestureRecord:
    record = GestureRecord(
        uid=uid,
        gesture_type=gesture_type,
        gesture_label=gesture_label,
        action=action,
        confidence=confidence,
        infer_ms=infer_ms,
        source=source,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def list_gesture_records(
    db: Session, *, uid: int | None = None, limit: int = 20, offset: int = 0
) -> list[GestureRecord]:
    """uid 为 None 时返回全站记录（管理员用），否则只返回该用户的。"""
    stmt = select(GestureRecord).order_by(GestureRecord.record_id.desc()).limit(limit).offset(offset)
    if uid is not None:
        stmt = stmt.where(GestureRecord.uid == uid)
    return list(db.scalars(stmt))


def count_gesture_records(db: Session, *, uid: int | None = None) -> int:
    stmt = select(func.count()).select_from(GestureRecord)
    if uid is not None:
        stmt = stmt.where(GestureRecord.uid == uid)
    return int(db.scalar(stmt) or 0)


def delete_gesture_record(db: Session, *, record_id: int, uid: int | None, is_admin: bool) -> bool:
    """删除记录。普通用户只能删自己的，管理员可删任意一条。"""
    record = db.get(GestureRecord, record_id)
    if record is None:
        return False
    if not is_admin and record.uid != uid:
        return False
    db.delete(record)
    db.commit()
    return True


def gesture_stats(db: Session, *, uid: int | None = None) -> dict[str, Any]:
    """统计：总数 + 按手势分组 + 最近 7 天每日数量（个人中心与后台都要用）。"""
    base = select(GestureRecord)
    if uid is not None:
        base = base.where(GestureRecord.uid == uid)
    records = list(db.scalars(base))

    by_type: dict[str, int] = {}
    for record in records:
        by_type[record.gesture_type] = by_type.get(record.gesture_type, 0) + 1

    cutoff = datetime.now(UTC) - timedelta(days=7)
    daily: dict[str, int] = {}
    for record in records:
        created = record.create_time
        if created is None:
            continue
        if created.tzinfo is None:  # SQLite 读回的是 naive，按 UTC 解释
            created = created.replace(tzinfo=UTC)
        if created >= cutoff:
            key = created.date().isoformat()
            daily[key] = daily.get(key, 0) + 1

    confidences = [r.confidence for r in records if r.confidence]
    return {
        "total": len(records),
        "by_type": dict(sorted(by_type.items(), key=lambda kv: -kv[1])),
        "daily": dict(sorted(daily.items())),
        "avg_confidence": round(sum(confidences) / len(confidences), 4) if confidences else 0.0,
    }


# --------------------------------------------------------------------------- 图片记录


def add_image_record(
    db: Session,
    *,
    uid: int | None,
    img_path: str,
    result: str = "",
    label: str = "",
    source: str = "upload",
    confidence: float = 0.0,
) -> ImageRecord:
    record = ImageRecord(
        uid=uid,
        img_path=img_path,
        result=result,
        label=label,
        source=source,
        confidence=confidence,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def list_image_records(
    db: Session, *, uid: int | None, limit: int = 20, offset: int = 0
) -> list[ImageRecord]:
    stmt = select(ImageRecord).order_by(ImageRecord.record_id.desc()).limit(limit).offset(offset)
    if uid is not None:
        stmt = stmt.where(ImageRecord.uid == uid)
    return list(db.scalars(stmt))


def count_image_records(db: Session, *, uid: int | None = None) -> int:
    stmt = select(func.count()).select_from(ImageRecord)
    if uid is not None:
        stmt = stmt.where(ImageRecord.uid == uid)
    return int(db.scalar(stmt) or 0)


# --------------------------------------------------------------------------- 问答记录


def add_chat_record(db: Session, *, uid: int | None, question: str, answer: str) -> ChatRecord:
    record = ChatRecord(uid=uid, question=question, answer=answer)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def list_chat_records(
    db: Session, *, uid: int | None, limit: int = 20, offset: int = 0
) -> list[ChatRecord]:
    stmt = select(ChatRecord).order_by(ChatRecord.chat_id.desc()).limit(limit).offset(offset)
    if uid is not None:
        stmt = stmt.where(ChatRecord.uid == uid)
    return list(db.scalars(stmt))


def count_chat_records(db: Session, *, uid: int | None = None) -> int:
    stmt = select(func.count()).select_from(ChatRecord)
    if uid is not None:
        stmt = stmt.where(ChatRecord.uid == uid)
    return int(db.scalar(stmt) or 0)


def overview_stats(db: Session) -> dict[str, int]:
    """后台首页四张卡片用。"""

    def count(model) -> int:  # noqa: ANN001
        return int(db.scalar(select(func.count()).select_from(model)) or 0)

    return {
        "users": count(User),
        "gesture_records": count(GestureRecord),
        "image_records": count(ImageRecord),
        "chat_records": count(ChatRecord),
    }

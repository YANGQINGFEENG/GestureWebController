"""四张业务表的 ORM 定义（对应需求文档第 5 章）。

表关系：
    user 1 ──< gesture_record   （手势识别日志，未登录用户 uid 为 null）
    user 1 ──< image_record     （图片识别，含上传 / 手势触发 / 截屏）
    user 1 ──< chat_record      （AI 问答）

约定：
- 主键名严格按需求文档：uid / record_id / chat_id，答辩核对表结构时可直接对上。
- 时间统一存 UTC（datetime.now(UTC)），展示层再转本地时区，避免换机器时区不同导致顺序错乱。
- 表结构只在 db/models.py 定义，API 层不写 SQL。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    """用户表。role 只有 user / admin 两种取值，见 docs/决策记录.md ADR-012。"""

    __tablename__ = "user"

    uid: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    # 列名沿用需求文档的 password，实际存的是 bcrypt 哈希（$2b$...），不是明文
    password_hash: Mapped[str] = mapped_column("password", String(128), nullable=False)
    nickname: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    create_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now()
    )

    gesture_records: Mapped[list["GestureRecord"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    image_records: Mapped[list["ImageRecord"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    chat_records: Mapped[list["ChatRecord"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def to_public(self) -> dict:
        """对外输出（绝不含密码哈希）。"""
        return {
            "uid": self.uid,
            "username": self.username,
            "nickname": self.nickname or self.username,
            "role": self.role,
            "create_time": self.create_time.isoformat() if self.create_time else None,
        }


class GestureRecord(Base):
    """手势识别记录表（核心表）：一次动作触发 = 一条记录。"""

    __tablename__ = "gesture_record"

    record_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uid: Mapped[int | None] = mapped_column(
        ForeignKey("user.uid", ondelete="CASCADE"), nullable=True, index=True
    )
    # 手势语义标识（peace / point / palm / like / xsign / rock），与模型类别解耦
    gesture_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    gesture_label: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    # 触发的动作：scroll_up / scroll_down / screenshot / confirm / image_recognition / screenshot_ai_search
    action: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    infer_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="camera")
    create_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now(), index=True
    )

    user: Mapped["User | None"] = relationship(back_populates="gesture_records")

    __table_args__ = (Index("ix_gesture_record_uid_time", "uid", "create_time"),)

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "uid": self.uid,
            "gesture_type": self.gesture_type,
            "gesture_label": self.gesture_label,
            "action": self.action,
            "confidence": round(float(self.confidence or 0.0), 4),
            "infer_ms": round(float(self.infer_ms or 0.0), 1),
            "source": self.source,
            "create_time": self.create_time.isoformat() if self.create_time else None,
        }


class ImageRecord(Base):
    """图片识别记录表：手动上传 / 手势触发 / 截屏识别 共用一张表，用 source 区分。"""

    __tablename__ = "image_record"

    record_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uid: Mapped[int | None] = mapped_column(
        ForeignKey("user.uid", ondelete="CASCADE"), nullable=True, index=True
    )
    img_path: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    result: Mapped[str] = mapped_column(Text, nullable=False, default="")
    label: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # upload / gesture / screenshot（M3 使用，先建列避免返工改表）
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="upload")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    create_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now(), index=True
    )

    user: Mapped["User | None"] = relationship(back_populates="image_records")

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "uid": self.uid,
            "img_path": self.img_path,
            "result": self.result,
            "label": self.label,
            "source": self.source,
            "confidence": round(float(self.confidence or 0.0), 4),
            "create_time": self.create_time.isoformat() if self.create_time else None,
        }


class ChatRecord(Base):
    """AI 问答记录表：一问一答一行。"""

    __tablename__ = "chat_record"

    chat_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uid: Mapped[int | None] = mapped_column(
        ForeignKey("user.uid", ondelete="CASCADE"), nullable=True, index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False, default="")
    answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    create_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now(), index=True
    )

    user: Mapped["User | None"] = relationship(back_populates="chat_records")

    def to_dict(self, preview: int = 0) -> dict:
        def clip(text: str) -> str:
            if preview and len(text) > preview:
                return text[:preview] + "…"
            return text

        return {
            "chat_id": self.chat_id,
            "uid": self.uid,
            "question": clip(self.question),
            "answer": clip(self.answer),
            "create_time": self.create_time.isoformat() if self.create_time else None,
        }

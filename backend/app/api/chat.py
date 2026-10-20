"""AI 问答接口：`POST /api/chat`（SSE 流式）+ `GET /api/chat/info`。

为什么用 SSE 而不是普通 JSON：
- 大模型逐字返回，用户能立刻看到"在答"，比转圈 20 秒体验好得多；
- 浏览器原生 `EventSource`/`ReadableStream` 就能读，不需要 WebSocket 那套连接管理；
- 单向推送，正好匹配"问 → 答"的语义。

事件格式（每条一个 `data:` 行，`\\n\\n` 结束）：

    data: {"type":"start","provider":"mock","model":"offline-rules","saved_hint":true}
    data: {"type":"delta","text":"当前支持这些手势："}
    data: {"type":"done","chat_id":12,"answer":"……","saved":true}
    data: {"type":"error","message":"模型接口返回 401：..."}

落库时机：流结束后写 `chat_record`，`chat_id` 随 `done` 事件返回，前端可以据此显示"已保存"。
数据库不可用 / 记录关闭时 `saved=false`，问答本身照常完成（ADR-006 的延续）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError

from backend.app.api.deps import MaybeDb, OptionalUser
from backend.app.core.config import load_app_config
from backend.app.db import repository
from backend.app.db.session import db_unavailable_reason
from backend.app.services import llm as llm_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # 让 nginx 之类的反代不要缓冲，否则流式会变成一次性
}


class ChatIn(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    context: str = Field("", max_length=4000, description="可选的图片来源上下文，如识别结果文本")


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _history(db, uid: int | None, limit: int) -> list[dict[str, str]]:
    """取最近几轮问答作为上下文；游客没有历史，直接空列表。"""
    if db is None or uid is None or limit <= 0:
        return []
    try:
        rows = repository.list_chat_records(db, uid=uid, limit=limit)
    except SQLAlchemyError as exc:
        logger.warning("读取问答历史失败（不影响本次回答）：%s", exc)
        return []
    messages: list[dict[str, str]] = []
    for row in reversed(rows):  # 列表是倒序，喂给模型要正序
        messages.append({"role": "user", "content": row.question})
        messages.append({"role": "assistant", "content": row.answer})
    return messages


@router.get("/chat/info", summary="当前问答模型信息")
def chat_info() -> dict:
    """前端据此显示"离线回答"还是"真实模型"，避免用户误以为是真 AI。"""
    return {"ok": True, "llm": llm_service.current_info().to_dict()}


@router.post("/chat", summary="AI 问答（SSE 流式）")
async def chat(payload: ChatIn, user: OptionalUser, db: MaybeDb) -> StreamingResponse:
    cfg = load_app_config()
    info = llm_service.current_info()
    history = _history(db, user.uid if user else None, cfg.llm.history)

    async def event_stream() -> AsyncIterator[str]:
        yield _sse(
            {
                "type": "start",
                "provider": info.provider,
                "model": info.model,
                "note": info.note,
                "persist": db is not None and cfg.records.enabled,
            }
        )

        parts: list[str] = []
        try:
            async for piece in llm_service.stream_answer(
                payload.question, context=payload.context, history=history
            ):
                parts.append(piece)
                yield _sse({"type": "delta", "text": piece})
        except asyncio.CancelledError:
            # 用户中途关页面：把已生成的部分存下来，再正常退出
            _persist(db, user, payload, "".join(parts), cfg, silent=True)
            raise
        except llm_service.LlmError as exc:
            yield _sse({"type": "error", "message": str(exc)})
            yield _sse({"type": "done", "chat_id": None, "saved": False, "answer": "".join(parts)})
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("问答失败")
            yield _sse({"type": "error", "message": f"回答失败：{exc}"})
            yield _sse({"type": "done", "chat_id": None, "saved": False, "answer": "".join(parts)})
            return

        answer = "".join(parts)
        chat_id = _persist(db, user, payload, answer, cfg)
        yield _sse(
            {
                "type": "done",
                "chat_id": chat_id,
                "answer": answer,
                "saved": chat_id is not None,
            }
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=SSE_HEADERS)


def _persist(db, user, payload: ChatIn, answer: str, cfg, silent: bool = False) -> int | None:
    """写问答记录。失败只记日志——问答是主功能，记录是附加能力。"""
    if not answer.strip():
        return None
    if db is None or not cfg.records.enabled:
        if not silent:
            reason = "记录功能已在配置中关闭" if db is not None else (db_unavailable_reason() or "数据库不可用")
            logger.info("问答未落库：%s", reason)
        return None
    try:
        record = repository.add_chat_record(
            db,
            uid=user.uid if user else None,
            question=payload.question,
            answer=answer,
        )
        return record.chat_id
    except SQLAlchemyError as exc:
        logger.warning("问答记录落库失败（不影响回答）：%s", exc)
        db.rollback()
        return None

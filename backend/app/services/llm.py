"""AI 问答：把问题（可带图片识别结果）交给大模型，流式吐回。

两种 provider（ADR-017）：
- `mock`   ：离线规则回答。不联网、不花钱、断网也能答辩演示；回答内容围绕本工具的手势与识别结论，
             不去猜用户想问的百科知识——猜错比不答更糟。
- `openai` ：任何 OpenAI 兼容的 `/chat/completions`（OpenAI、DeepSeek、通义、本地 Ollama 通用），
             逐行读 SSE，边收边吐。

职责边界：本模块只管"问题 → 文本片段"。落库、鉴权、SSE 编码都在 `api/chat.py`。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx

from backend.app.core.config import LlmConfig, load_app_config, load_gesture_map

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是 GestureWebController 的助手，这是一个基于 YOLO 的网页手势控制工具。

可用手势（部分）：✌️ 下翻页、☝️ 上翻页、🖐️ 截屏、👍 确定、🤞 触发图片识别、🤟 截屏 + AI 搜索。

回答规则：
1. 只回答与本工具、手势操控、图片识别、网页交互相关的问题；无关问题礼貌说明你的定位，不要硬答。
2. 图片识别结果来自 YOLO 目标检测（只判断"有没有手势、是哪一种、置信度多少"），
   不代表理解了画面含义。不要把它说成"看懂图片内容"。
3. 不知道就说不知道，不要编造接口名、参数或数据。
4. 中文回答，简洁，不超过 200 字。"""


class LlmError(RuntimeError):
    """模型调用失败（网络、鉴权、限流等），信息可直接展示给用户。"""


@dataclass(frozen=True)
class LlmInfo:
    provider: str
    model: str
    ready: bool
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "ready": self.ready,
            "note": self.note,
        }


def current_info(cfg: LlmConfig | None = None) -> LlmInfo:
    cfg = cfg or load_app_config().llm
    if cfg.is_mock:
        return LlmInfo("mock", "offline-rules", True, "离线规则回答：未接大模型，回答仅基于本工具配置")
    if not cfg.api_key:
        return LlmInfo(cfg.provider, cfg.model, False, "缺少 GWC_LLM_API_KEY，已回退到离线回答")
    return LlmInfo(cfg.provider, cfg.model, True, "")


async def stream_answer(
    question: str,
    *,
    context: str = "",
    history: list[dict[str, str]] | None = None,
    cfg: LlmConfig | None = None,
) -> AsyncIterator[str]:
    """产出回答的文本片段。调用方负责拼接与落库。"""
    cfg = cfg or load_app_config().llm
    if cfg.is_mock or not cfg.api_key:
        async for piece in _mock_stream(question, context):
            yield piece
        return

    async for piece in _openai_stream(cfg, question, context, history or []):
        yield piece


# --------------------------------------------------------------------------- 离线回答


def _gesture_lines() -> list[str]:
    """手势清单直接从配置生成，不在这里硬编码（AGENTS.md 约定 2）。"""
    return [
        f"{g.emoji} {g.label} → {g.action_label or g.action}"
        for g in load_gesture_map().gestures
    ]


def _mock_answer(question: str, context: str) -> str:
    q = question.strip()
    ctx = context.strip()

    if ctx:
        head = f"关于这次识别结果（{ctx[:60]}{'…' if len(ctx) > 60 else ''}）："
        if "未识别" in ctx or "未检测到" in ctx:
            body = (
                "模型没有在这张图里找到六种预设手势。常见原因是手离镜头太远、"
                "手部被遮挡、或光线太暗。把手抬到画面中央、让手掌完整入画，再试一次。"
            )
        else:
            body = (
                "这是 YOLO 目标检测的结论，包含手势类别与置信度——置信度高说明模型越确定，"
                "但不代表它读懂了画面含义。需要理解截图内容时，可以把这句识别结果一起发给我，"
                "我再结合文字做解读。"
            )
        return head + body

    if any(k in q for k in ("什么手势", "哪些手势", "支持", "怎么用", "如何使用")):
        return "当前支持这些手势：\n" + "\n".join(_gesture_lines()) + "\n手势连续 3 帧命中才触发，避免抖动误操作。"

    if any(k in q for k in ("置信度", "阈值", "误触")):
        return (
            "置信度是模型对「这一帧是什么手势」的把握程度，0~1。系统用两段式阈值：先以 0.3 的低门槛取候选，"
            "再由每种手势自己的门槛决定算不算数（多数是 0.7，🤟 因为借用了近似类别设为 0.45）；"
            "前端再要求连续 3 帧命中且同一手势冷却 800ms，才真正执行动作。"
        )

    if "截屏" in q:
        return (
            "🖐️ 会截取当前网页可视区，走的是 html2canvas：纯前端、不需要额外授权、也不会截到桌面其他软件。"
            "🤟 在此基础上把截图直接送去识别，整条链路实测在 0.3 秒左右。"
        )

    if any(k in q for k in ("识别", "图片", "图像")):
        return (
            "图片识别分两层：YOLO 负责检测「图里有没有手势、是哪一种」；"
            "至于「这张截图在讲什么」，属于语义理解，交给问答这边来做——"
            "两层结果分开存，检测结论进 image_record，解读进 chat_record，避免把两种可信度混在一起。"
        )

    if any(k in q for k in ("数据库", "记录", "历史")):
        return "每次手势触发、图片识别、问答都会入库（手势记录 / 图片识别 / 问答三张表，外键关联用户）。个人中心可以查历史并删除。"

    return (
        "我是这个手势控制工具的助手，可以聊手势操控、图片识别、截屏链路和记录相关的问题。\n"
        "当前是离线规则回答（未配置大模型 Key），复杂问题建议配置 GWC_LLM_API_KEY 后使用真实模型。"
    )


async def _mock_stream(question: str, context: str) -> AsyncIterator[str]:
    """把整段回答切成小块吐出去，模拟真实流式，顺便让前端滚动效果一致。"""
    text = _mock_answer(question, context)
    size = 12
    for i in range(0, len(text), size):
        yield text[i : i + size]
        await asyncio.sleep(0.02)


# --------------------------------------------------------------------------- OpenAI 兼容


def build_messages(question: str, context: str, history: list[dict[str, str]]) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for item in history[-8:]:
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content[:2000]})
    user_content = question.strip()
    if context.strip():
        user_content += f"\n\n（本次图片识别结果：{context.strip()[:500]}）"
    messages.append({"role": "user", "content": user_content})
    return messages


async def _openai_stream(
    cfg: LlmConfig,
    question: str,
    context: str,
    history: list[dict[str, str]],
) -> AsyncIterator[str]:
    payload = {
        "model": cfg.model,
        "messages": build_messages(question, context, history),
        "stream": True,
        "temperature": 0.6,
    }
    headers = {"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"}
    url = f"{cfg.base_url.rstrip('/')}/chat/completions"

    try:
        async with httpx.AsyncClient(timeout=cfg.timeout) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", "replace")[:300]
                    raise LlmError(f"模型接口返回 {resp.status_code}：{body}")
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        data = json.loads(chunk)
                    except json.JSONDecodeError:
                        logger.debug("忽略无法解析的流片段：%s", chunk[:80])
                        continue
                    choices = data.get("choices") or [{}]
                    delta = (choices[0].get("delta") or {}).get("content")
                    if delta:
                        yield delta
    except httpx.HTTPError as exc:
        raise LlmError(f"连不上模型服务（{cfg.base_url}）：{exc}") from exc

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""追加一条开发日志，并刷新进度看板的 front matter。

跨机器协作的关键小工具：不用手写时间戳和主机名，一条命令把"谁、在哪台机器、哪个分支、干了什么"记下来。

用法：
    python scripts/log_progress.py "实现 detector 封装，单帧 96ms"
    python scripts/log_progress.py "修好摄像头释放" --next "开始 M1 第 2 项"
    python scripts/log_progress.py "M0 完成" --milestone M1 --task "前端 SDK 采集模块" --progress 25%
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "docs" / "开发日志.md"
BOARD = ROOT / "docs" / "开发进度.md"


def git(*args: str) -> str:
    try:
        out = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=10
        )
        return out.stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def append_log(now: dt.datetime, host: str, branch: str, sha: str, body: list[str]) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    text = LOG.read_text(encoding="utf-8") if LOG.exists() else "# 开发日志\n"
    day = now.strftime("%Y-%m-%d")
    if f"## {day}" not in text:
        text = text.rstrip() + f"\n\n## {day}\n"
    entry = (
        f"\n### {now.strftime('%H:%M')} · {host} · {branch}@{sha}\n"
        + "\n".join(f"- {line}" for line in body)
        + "\n"
    )
    if not text.endswith("\n"):
        text += "\n"
    LOG.write_text(text + entry, encoding="utf-8")


def touch_board(now: dt.datetime, host: str, fields: dict[str, str]) -> list[str]:
    if not BOARD.exists():
        return [f"未找到 {BOARD.relative_to(ROOT)}，跳过看板更新"]

    text = BOARD.read_text(encoding="utf-8")
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
    if not m:
        return ["进度看板缺少 front matter，跳过"]

    updates = {"updated_at": now.strftime("%Y-%m-%d %H:%M"), "updated_by": f"ai-agent ({host})"}
    updates.update({k: v for k, v in fields.items() if v})

    block = m.group(1)
    for key, value in updates.items():
        pattern = re.compile(rf"^{re.escape(key)}:.*$", re.M)
        line = f"{key}: {value}"
        if pattern.search(block):
            block = pattern.sub(line, block, count=1)
        else:
            block += f"\n{line}"

    new_text = f"---\n{block}\n---\n" + text[m.end():]
    BOARD.write_text(new_text, encoding="utf-8")
    return [f"{k} = {v}" for k, v in updates.items()]


def main() -> int:
    parser = argparse.ArgumentParser(description="追加开发日志并刷新进度看板")
    parser.add_argument("message", nargs="*", help="本次做了什么")
    parser.add_argument("--next", dest="next_action", default="", help="下一步计划")
    parser.add_argument("--blocker", default="", help="当前卡点")
    parser.add_argument("--milestone", default="", help="更新 current_milestone，如 M1")
    parser.add_argument("--task", default="", help="更新 current_task")
    parser.add_argument("--progress", default="", help="更新 overall_progress，如 25%%")
    args = parser.parse_args()

    now = dt.datetime.now()
    host = socket.gethostname()
    branch = git("rev-parse", "--abbrev-ref", "HEAD") or "?"
    sha = git("rev-parse", "--short", "HEAD") or "?"

    body = [f"做了什么：{' '.join(args.message).strip() or '(未填写)'}"]
    if args.blocker:
        body.append(f"卡点：{args.blocker}")
    if args.next_action:
        body.append(f"下一步：{args.next_action}")

    append_log(now, host, branch, sha, body)
    changed = touch_board(
        now,
        host,
        {
            "current_milestone": args.milestone,
            "current_task": args.task,
            "overall_progress": args.progress,
            "next_action": args.next_action,
        },
    )

    print(f"[日志] 已追加到 docs/开发日志.md（{host} · {branch}@{sha}）")
    for line in changed:
        print(f"[看板] {line}")
    print("\n记得补一句 docs/开发进度.md 里的清单勾选，然后提交。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

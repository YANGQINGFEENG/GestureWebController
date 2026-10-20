#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一条命令起开发环境：后端 API + 演示页静态服务。

用法（必须用仓库里的虚拟环境解释器）：
    .venv/Scripts/python scripts/start_dev.py           # Windows
    .venv/bin/python scripts/start_dev.py               # macOS / Linux

可选参数：
    --api-port 8000 --web-port 8080 --no-preload

为什么不用两个终端：跨机器开发时最容易漏的是"只起了后端、忘了静态服务"，
然后打开 file:// 发现模块加载失败（ES Module 不允许 file:// 下的相对导入）。
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def port_busy(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex((host, port)) == 0


def wait_ready(port: int, timeout: float = 25.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_busy(port):
            return True
        time.sleep(0.4)
    return False


def main() -> int:
    # 输出被重定向到文件时默认是块缓冲，提示可能迟迟不出现，这里强制行缓冲
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:  # noqa: BLE001
        pass

    parser = argparse.ArgumentParser(description="启动手势控制项目的开发环境")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--web-port", type=int, default=8080)
    parser.add_argument("--no-preload", action="store_true", help="不预加载模型（首帧会慢约 3s）")
    args = parser.parse_args()

    for port, name in ((args.api_port, "API"), (args.web_port, "静态服务")):
        if port_busy(port):
            print(f"[!] {name}端口 {port} 已被占用，请先关掉占用进程或换端口")
            return 1

    if not (ROOT / "models").glob("*.pt"):
        print("[!] models/ 下没有权重，先跑：python scripts/download_model.py")

    env = dict(os.environ)
    if not args.no_preload:
        env["GWC_PRELOAD"] = "1"

    procs: list[subprocess.Popen] = []
    try:
        procs.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "backend.app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.api_port),
                ],
                cwd=ROOT,
                env=env,
            )
        )
        procs.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "http.server",
                    str(args.web_port),
                    "--bind",
                    "127.0.0.1",
                    "--directory",
                    str(ROOT),
                ],
                cwd=ROOT,
            )
        )

        print("启动中…（后端首次加载模型约 3~20 秒）")
        if not wait_ready(args.api_port):
            print("[!] 后端没有起来，检查上面的报错")
            return 1

        print()
        print("=" * 62)
        print(f"  演示页   http://127.0.0.1:{args.web_port}/frontend/pages/index.html")
        print(f"  接口文档 http://127.0.0.1:{args.api_port}/docs")
        print(f"  健康检查 http://127.0.0.1:{args.api_port}/api/health")
        print("=" * 62)
        print("  没有摄像头？在页面上点「用图片序列」，选几张手势图即可验证全链路")
        print("  Ctrl+C 结束")
        print()

        while all(p.poll() is None for p in procs):
            time.sleep(0.5)
        return 0

    except KeyboardInterrupt:
        print("\n正在关闭…")
        return 0
    finally:
        for proc in procs:
            if proc.poll() is None:
                try:
                    if os.name == "nt":
                        proc.send_signal(signal.CTRL_BREAK_EVENT)
                    proc.terminate()
                except Exception:  # noqa: BLE001
                    pass
        for proc in procs:
            try:
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                proc.kill()


if __name__ == "__main__":
    sys.exit(main())

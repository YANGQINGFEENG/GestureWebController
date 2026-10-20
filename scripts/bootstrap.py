#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一键自举：把"clone 下来到能打开演示页"压成一条命令。

为什么不用 shell 写全部逻辑：Windows 的 .bat 和类 Unix 的 .sh 语法差太远，
中文输出还容易乱码。这里把判断都放在 Python 里，start.bat / start.sh 只负责
找到解释器并调用本文件，两边行为完全一致。

做四件事（已完成的会跳过，重复执行安全）：
  1. 没有 .venv 就建一个，并装 backend/requirements.txt
  2. 没有模型权重就下载（22MB，不入库）
  3. 自检手势映射与模型类别是否对得上
  4. 调用 scripts/start_dev.py 同时起后端（8000）与静态服务（8080）

用法：
    python scripts/bootstrap.py              # 全流程，最后起服务
    python scripts/bootstrap.py --check      # 只做 1~3，打印环境结论，不起服务
    python scripts/bootstrap.py --no-preload # 透传给 start_dev.py
    python scripts/bootstrap.py --api-port 8010 --web-port 8090

退出码：0 正常；1 自举失败（依赖装不上 / 权重下载失败 / 配置对不上）。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
IS_WIN = os.name == "nt"


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")


def say(text: str) -> None:
    print(text, flush=True)


def step(n: int, total: int, text: str) -> None:
    say(f"\n[{n}/{total}] {text}")


def run(cmd: list[str], *, cwd: Path | None = None, quiet: bool = False) -> int:
    """执行子进程并把输出直接透传到当前终端（用户要看得见进度）。"""
    if not quiet:
        say("  $ " + " ".join(str(c) for c in cmd))
    return subprocess.call([str(c) for c in cmd], cwd=str(cwd or ROOT))


# --------------------------------------------------------------------------- 1. 虚拟环境

REQUIRED_MODULES = ("fastapi", "uvicorn", "sqlalchemy", "jwt", "bcrypt", "ultralytics", "httpx", "PIL")


def deps_ok(python: Path) -> bool:
    """快速探针：能 import 关键包就认为依赖齐了，不跑 pip（pip 每次要几秒）。"""
    code = "import importlib\n" + "\n".join(
        f"importlib.import_module({m!r})" for m in REQUIRED_MODULES
    )
    try:
        return (
            subprocess.run(
                [str(python), "-c", code],
                cwd=str(ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=120,
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


def ensure_venv() -> Path:
    """返回可用的 venv 解释器；必要时创建并安装依赖。"""
    target = venv_python()
    if target.exists():
        say(f"  ✓ 虚拟环境已存在：{target.relative_to(ROOT)}")
    else:
        say("  虚拟环境不存在，正在创建（约 10 秒）…")
        code = run([sys.executable, "-m", "venv", str(VENV)])
        if code != 0 or not target.exists():
            say("  ✗ 创建虚拟环境失败。请确认 Python 3.10+ 已安装并在 PATH 里。")
            raise SystemExit(1)

    if deps_ok(target):
        say("  ✓ 依赖已就绪")
        return target

    say("  依赖缺失或不完整，开始安装（首次约 1~3 分钟，ultralytics 会带上 torch，约 200MB）…")
    run([str(target), "-m", "pip", "install", "--upgrade", "pip", "-q"])
    code = run([str(target), "-m", "pip", "install", "-r", str(ROOT / "backend" / "requirements.txt")])
    if code != 0:
        say("\n  ✗ 依赖安装失败。常见原因：网络受限。可以换源重试：")
        say(f"    {target} -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r backend/requirements.txt")
        raise SystemExit(1)
    if not deps_ok(target):
        say("  ✗ 依赖装了但仍无法导入，请检查上面的 pip 输出")
        raise SystemExit(1)
    say("  ✓ 依赖安装完成")
    return target


# --------------------------------------------------------------------------- 2. 权重


def ensure_model(python: Path) -> None:
    models_dir = ROOT / "models"
    weights = list(models_dir.glob("*.pt")) if models_dir.exists() else []
    if weights:
        total_mb = sum(w.stat().st_size for w in weights) / 1048576
        names = "、".join(w.name for w in weights)
        say(f"  ✓ 已有权重：{names}（{total_mb:.1f}MB）")
        return

    say("  没有找到权重，开始下载（约 22MB，从 GitHub 拉取预训练模型）…")
    code = run([str(python), str(ROOT / "scripts" / "download_model.py")])
    if code != 0:
        say("\n  ✗ 权重下载失败。可以手动下载后放到 models/ 目录，见 docs/交接说明.md")
        raise SystemExit(1)
    say("  ✓ 权重就绪")


# --------------------------------------------------------------------------- 3. 配置自检


def check_config(python: Path) -> None:
    code = run([str(python), str(ROOT / "scripts" / "check_gesture_map.py")])
    if code != 0:
        say("\n  ✗ 手势映射与模型类别对不上，先修 config/gesture_map.json 再启动")
        raise SystemExit(1)


# --------------------------------------------------------------------------- 主流程


def main() -> int:
    parser = argparse.ArgumentParser(description="GestureWebController 一键自举")
    parser.add_argument("--check", action="store_true", help="只检查环境，不启动服务")
    # 其余参数原样透传给 start_dev.py
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--web-port", type=int, default=8080)
    parser.add_argument("--no-preload", action="store_true")
    args = parser.parse_args()

    say("=" * 60)
    say(" GestureWebController 环境自举")
    say(f" 仓库：{ROOT}")
    say(f" 平台：{sys.platform} / Python {sys.version.split()[0]}")
    say("=" * 60)

    total = 4
    step(1, total, "检查虚拟环境与依赖")
    python = ensure_venv()

    # 如果当前不是用 venv 解释器跑的（比如直接 python scripts/bootstrap.py），
    # 后面的步骤也必须用 venv 解释器，否则 import 会失败
    if Path(sys.executable).resolve() != python.resolve():
        say("  提示：后续步骤改用虚拟环境解释器执行")

    step(2, total, "检查模型权重")
    ensure_model(python)

    step(3, total, "自检手势映射与模型类别")
    check_config(python)

    if args.check:
        say("\n" + "-" * 60)
        say("✓ 环境就绪。去掉 --check 即可启动：")
        say(f"  {python} scripts/bootstrap.py")
        return 0

    step(4, total, "启动后端与静态服务")
    cmd = [str(python), str(ROOT / "scripts" / "start_dev.py"),
           "--api-port", str(args.api_port), "--web-port", str(args.web_port)]
    if args.no_preload:
        cmd.append("--no-preload")
    say("  提示：Ctrl+C 同时停掉两个服务\n")
    return run(cmd)


if __name__ == "__main__":
    sys.exit(main())

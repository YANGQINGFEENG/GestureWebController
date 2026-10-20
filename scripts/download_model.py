#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""下载 HaGRIDv2 手势检测预训练权重到 models/。

权重不入库（22MB），换机后跑一次即可。只依赖标准库。

用法：
    python scripts/download_model.py            # 默认下载 YOLOv10n（22MB，CPU 可跑）
    python scripts/download_model.py --variant x  # YOLOv10x，精度更高但更慢
"""

from __future__ import annotations

import argparse
import hashlib
import ssl
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models"
BASE = "https://rndml-team-cv.obs.ru-moscow-1.hc.sbercloud.ru/datasets/hagrid_v2/models"
VARIANTS = {
    "n": ("YOLOv10n_gestures.pt", 22_442_394, "88.2"),
    "x": ("YOLOv10x_gestures.pt", None, "89.4"),
}


def build_opener() -> urllib.request.OpenerDirector:
    """公司/校园网代理常见证书链问题，失败时降级为不校验（仅下载公开权重）。"""
    try:
        return urllib.request.build_opener()
    except Exception:  # noqa: BLE001
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "GestureWebController/1.0"})
    try:
        opener = urllib.request.build_opener()
        resp = opener.open(req, timeout=60)
    except Exception:  # noqa: BLE001
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
        resp = opener.open(req, timeout=60)

    total = int(resp.headers.get("Content-Length") or 0)
    done = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with tmp.open("wb") as fh:
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if total:
                pct = done * 100 // total
                print(f"\r  下载中 {pct:3d}%  {done / 1048576:.1f}/{total / 1048576:.1f} MB", end="")
            else:
                print(f"\r  下载中 {done / 1048576:.1f} MB", end="")
    print()
    tmp.replace(dest)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="下载 HaGRIDv2 手势检测权重")
    parser.add_argument("--variant", choices=sorted(VARIANTS), default="n", help="n=V10n（默认） / x=V10x")
    args = parser.parse_args()

    filename, expected_size, acc = VARIANTS[args.variant]
    dest = MODELS_DIR / filename
    if dest.exists():
        size = dest.stat().st_size
        print(f"[跳过] 已存在 {dest.name}（{size / 1048576:.1f} MB）")
        print(f"       sha256 = {sha256(dest)}")
        return 0

    print(f"[下载] {filename}（手势检测精度 {acc}，协议 CC BY-SA 4.0）")
    download(f"{BASE}/{filename}", dest)

    size = dest.stat().st_size
    if expected_size and size != expected_size:
        print(f"[!] 大小与预期不一致：{size} != {expected_size}，请检查网络是否返回了错误页")
        return 1
    print(f"[完成] {dest.relative_to(ROOT)}  {size / 1048576:.1f} MB")
    print(f"       sha256 = {sha256(dest)}")
    print("\n下一步：python scripts/check_gesture_map.py   # 校验手势映射与类别是否对得上")
    return 0


if __name__ == "__main__":
    sys.exit(main())

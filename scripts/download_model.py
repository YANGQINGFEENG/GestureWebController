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
    # 名称, 预期字节数, 精度, sha256
    "n": (
        "YOLOv10n_gestures.pt",
        22_442_394,
        "88.2",
        "bf628ce3a1638ab19a7ab635c0f674cfec2988989f42f1eef394a6dce5a35b9f",
    ),
    "x": ("YOLOv10x_gestures.pt", None, "89.4", None),
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
    parser.add_argument("--force", action="store_true", help="已存在也重新下载（文件损坏时用）")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="只校验已有文件，不下载（从别的电脑拷过来的权重用这个确认完整性）",
    )
    args = parser.parse_args()

    filename, expected_size, acc, expected_hash = VARIANTS[args.variant]
    dest = MODELS_DIR / filename

    def verify(path: Path) -> bool:
        """返回是否与预期一致；没有预期值就只报告数值。"""
        size = path.stat().st_size
        digest = sha256(path)
        print(f"       文件  {path.name}  {size / 1048576:.1f} MB")
        print(f"       sha256 = {digest}")
        ok = True
        if expected_size and size != expected_size:
            print(f"       [!] 大小与预期不符（应为 {expected_size} 字节），可能没下完或下成了错误页")
            ok = False
        if expected_hash and digest != expected_hash:
            print(f"       [!] sha256 与预期不符（应为 {expected_hash}）")
            ok = False
        if ok and (expected_size or expected_hash):
            print("       [ok] 校验通过")
        return ok

    if args.verify:
        if not dest.exists():
            print(f"[!] 文件不存在：{dest}")
            print("    下载：python scripts/download_model.py")
            return 1
        print(f"[校验] {dest.name}")
        return 0 if verify(dest) else 1

    if dest.exists() and not args.force:
        print(f"[跳过] 已存在 {dest.name}")
        ok = verify(dest)
        if not ok:
            print("\n文件不完整。重新下载：python scripts/download_model.py --force")
            return 1
        print("\n下一步：python scripts/check_gesture_map.py")
        return 0

    print(f"[下载] {filename}（手势检测精度 {acc}，协议 CC BY-SA 4.0）")
    print(f"       来源 {BASE}/{filename}")
    print("       如果卡住或失败：见 docs/交接说明.md「权重怎么拿到新电脑」一节")
    download(f"{BASE}/{filename}", dest)

    if not verify(dest):
        print("\n[失败] 文件校验不通过，已保留在磁盘供排查；重试：python scripts/download_model.py --force")
        return 1
    print("\n下一步：python scripts/check_gesture_map.py   # 校验手势映射与类别是否对得上")
    return 0


if __name__ == "__main__":
    sys.exit(main())

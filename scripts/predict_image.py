#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""在本地图片上跑一次手势检测，不需要启动服务。

用途：用手机拍几张手势照片丢进来，立刻知道识别率与耗时——比开摄像头试快得多。

用法：
    python scripts/predict_image.py photos/peace.jpg
    python scripts/predict_image.py photos/                # 整个目录
    python scripts/predict_image.py photos/ --repeat 5    # 测平均耗时
    python scripts/predict_image.py photos/ --annotate out/  # 输出画框图
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.app.services.detector import GestureDetector  # noqa: E402

SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def collect(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            files.extend(sorted(x for x in p.iterdir() if x.suffix.lower() in SUFFIXES))
        elif p.is_file():
            files.append(p)
        else:
            print(f"[跳过] 不存在：{raw}")
    return files


_FONT_CANDIDATES = (
    "C:/Windows/Fonts/msyh.ttc",  # 微软雅黑（Windows）
    "C:/Windows/Fonts/simhei.ttf",  # 黑体
    "/System/Library/Fonts/PingFang.ttc",  # 苹方（macOS）
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",  # Noto CJK（Linux）
)


def _load_font(size: int = 16):
    """优先加载中文字体；都没有则返回 None，标注文字退回英文类名。"""
    from PIL import ImageFont

    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return None


def annotate(src: Path, result: dict, out_dir: Path) -> Path:
    from PIL import Image, ImageDraw

    image = Image.open(src).convert("RGB")
    draw = ImageDraw.Draw(image)
    font = _load_font(16)
    for g in result["gestures"]:
        x1, y1, x2, y2 = g["box"]
        # 无中文字体时退回英文类名，避免画出乱码方块
        text = f"{g['label']} {g['conf']:.2f}" if font else f"{g['class']} {g['conf']:.2f}"
        draw.rectangle([x1, y1, x2, y2], outline=(255, 59, 48), width=3)
        draw.text((x1 + 4, max(y1 - 18, 2)), text, fill=(255, 59, 48), font=font)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{src.stem}_detected{src.suffix}"
    image.save(target)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="本地图片手势检测")
    parser.add_argument("paths", nargs="+", help="图片或目录")
    parser.add_argument("--repeat", type=int, default=1, help="每张图重复推理次数，用于测平均耗时")
    parser.add_argument("--annotate", type=Path, help="把画了框的图输出到该目录")
    parser.add_argument("--imgsz", type=int, help="推理分辨率，覆盖 config/model.yaml")
    parser.add_argument("--conf", type=float, help="置信度阈值，覆盖 config/model.yaml")
    args = parser.parse_args()

    files = collect(args.paths)
    if not files:
        print("没有找到可用图片")
        return 1

    detector = GestureDetector()
    started = time.perf_counter()
    detector.load()
    print(f"[模型] {detector.model_cfg.path.name} 加载耗时 {(time.perf_counter() - started) * 1000:.0f} ms\n")

    total_ms = 0.0
    hits = 0
    for path in files:
        data = path.read_bytes()
        result: dict = {}
        for _ in range(max(1, args.repeat)):
            result = detector.predict_bytes(data, conf=args.conf, imgsz=args.imgsz)
        total_ms += result["infer_ms"]

        gestures = result["gestures"]
        if gestures:
            hits += 1
            detail = "，".join(f"{g['label']}({g['class']}) {g['conf']:.2f}" for g in gestures)
        else:
            detail = "未识别到手势"
        print(f"{path.name:<28} {result['infer_ms']:>7.1f} ms  {detail}")

        if args.annotate:
            saved = annotate(path, result, args.annotate)
            print(f"{'':<28} → 已保存 {saved.relative_to(ROOT) if saved.is_relative_to(ROOT) else saved}")

    count = len(files)
    print(f"\n合计 {count} 张，命中 {hits} 张，平均 {total_ms / count:.1f} ms/张")
    if detector.model_cfg.device == "cpu" and total_ms / count > 300:
        print("提示：平均耗时超过 300ms，可下调 config/model.yaml 的 imgsz（如 480）再测。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

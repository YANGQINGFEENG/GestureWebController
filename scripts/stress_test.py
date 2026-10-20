#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""对单张手势图做降质压力测试，模拟真实摄像头条件。

用途：判断某个手势在「分辨率不足 / 压缩 / 模糊 / 暗光 / 过曝 / 轻微倾斜」下还能不能识别，
得出的是前端采集参数的下限（帧宽最小多少、需不需要补光），而不是实验室里的最好成绩。

用法：
    python scripts/stress_test.py photos/peace.jpg
    python scripts/stress_test.py photos/peace.jpg --expect peace
    python scripts/stress_test.py photos/peace.jpg --save out/   # 保存降质样本，便于人工核对
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageEnhance, ImageFilter  # noqa: E402

from backend.app.services.detector import GestureDetector  # noqa: E402


def to_jpeg(img: Image.Image, quality: int = 85) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def flatten(img: Image.Image) -> Image.Image:
    """透明背景压到白底——PNG 抠图直接转 RGB 会把透明区域变成黑色，影响检测。"""
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        canvas = Image.new("RGB", img.size, (255, 255, 255))
        canvas.paste(img, (0, 0), img)
        return canvas
    return img.convert("RGB")


def variants(base: Image.Image, width: int = 640):
    """产出 (条件名, 图像)。width 为降质基准宽度，也是真实摄像头帧的典型宽度。"""

    def fit(img: Image.Image, w: int) -> Image.Image:
        if img.width == w:
            return img
        h = max(1, int(img.height * w / img.width))
        return img.resize((w, h), Image.LANCZOS)

    yield "原始尺寸", base
    for w in (640, 480, 360, 320, 240):
        if w < base.width:
            yield f"缩放到 {w}px", fit(base, w)
    frame = fit(base, width)
    for q in (70, 40, 20):
        yield f"JPEG q{q}", frame
    yield "模糊 r=1.5", frame.filter(ImageFilter.GaussianBlur(1.5))
    yield "模糊 r=3", frame.filter(ImageFilter.GaussianBlur(3))
    for b in (0.4, 0.25):
        yield f"暗光 {int(b * 100)}%", ImageEnhance.Brightness(frame).enhance(b)
    yield "过曝 1.6x", ImageEnhance.Brightness(frame).enhance(1.6)
    yield "低对比 50%", ImageEnhance.Contrast(frame).enhance(0.5)
    for deg in (8, 15):
        yield f"旋转 {deg}°", frame.rotate(deg, expand=True, fillcolor=(255, 255, 255))


def main() -> int:
    parser = argparse.ArgumentParser(description="单张手势图降质压力测试")
    parser.add_argument("path", type=Path, help="待测图片")
    parser.add_argument("--expect", help="期望的模型类别名（如 peace），用于判断命中的是否正确")
    parser.add_argument("--save", type=Path, help="把降质样本保存到该目录，便于人工核对")
    args = parser.parse_args()

    if not args.path.is_file():
        print(f"图片不存在：{args.path}")
        return 1

    base = flatten(Image.open(args.path))
    detector = GestureDetector()
    detector.load()
    expect = args.expect

    print(f"图片：{args.path.name}  {base.width}x{base.height}")
    print(f"{'条件':<16}{'耗时':>9}  {'识别结果':<32}判定")
    print("-" * 76)

    hit = miss = wrong = 0
    hit_widths: list[int] = []
    for name, img in variants(base):
        result = detector.predict_bytes(to_jpeg(img))
        gestures = result["gestures"]

        if args.save:
            args.save.mkdir(parents=True, exist_ok=True)
            safe = name.replace(" ", "_").replace("=", "").replace("°", "deg")
            img.save(args.save / f"{args.path.stem}_{safe}.jpg", quality=85)

        if not gestures:
            verdict, detail = "❌ 漏检", "未识别到手势"
            miss += 1
        else:
            top = max(gestures, key=lambda g: g["conf"])
            detail = f"{top['id']}({top['class']}) {top['conf']:.2f}"
            if expect and top["class"] != expect:
                verdict = f"⚠️ 误判为 {top['class']}"
                wrong += 1
            else:
                verdict = "✅ 命中"
                hit += 1
                if name.startswith("缩放到"):
                    hit_widths.append(int(name.split()[1].rstrip("px")))
        print(f"{name:<16}{result['infer_ms']:>8.1f}ms  {detail:<32}{verdict}")

    total = hit + miss + wrong
    print("-" * 76)
    print(f"共 {total} 种条件：命中 {hit}，误判 {wrong}，漏检 {miss}")
    if hit_widths:
        print(f"仍能命中的最小帧宽：{min(hit_widths)}px → SDK 抽帧宽度不要低于此值（建议留一档余量）")
    else:
        print("缩放条件下全部漏检 → 该图本身手部占比太小，先确认原图能否识别")
    return 0


if __name__ == "__main__":
    sys.exit(main())

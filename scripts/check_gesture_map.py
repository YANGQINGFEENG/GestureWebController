#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""校验 config/gesture_map.json 与模型权重是否对得上。

用途：改完手势映射后跑一次，立刻知道"配置里的类别名，模型里到底有没有"。
只依赖标准库，不需要装 torch / ultralytics。

用法：
    python scripts/check_gesture_map.py
    python scripts/check_gesture_map.py --model models/YOLOv10n_gestures.pt
"""

from __future__ import annotations

import argparse
import json
import pickletools
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAP_PATH = ROOT / "config" / "gesture_map.json"
ALLOWED_ACTIONS = {
    "scroll_up",
    "scroll_down",
    "screenshot",
    "confirm",
    "image_recognition",
    "screenshot_ai_search",
}
# 类别名形态：小写字母开头，允许数字与下划线（ok、one 这类短名也不能漏）
CLASS_RE = re.compile(r"^[a-z][a-z0-9_]+$")


def read_model_classes(pt_path: Path) -> list[str]:
    """从 ultralytics 的 .pt（本质是 zip）里抠出 names 字典的类别名，无需 torch。"""
    with zipfile.ZipFile(pt_path) as zf:
        pkl = next((n for n in zf.namelist() if n.endswith("data.pkl")), None)
        if pkl is None:
            raise ValueError(f"{pt_path.name} 里找不到 data.pkl，可能不是 ultralytics 检查点")
        data = zf.read(pkl)

    names: list[str] = []
    collecting = False
    for _, arg, _ in pickletools.genops(data):
        if not isinstance(arg, str):
            continue
        if arg == "names":
            collecting = True
            continue
        if collecting:
            if CLASS_RE.match(arg):
                if arg not in names:
                    names.append(arg)
            elif names:
                break  # names 字典结束
    return names


def find_default_model() -> Path | None:
    candidates = sorted((ROOT / "models").glob("*.pt"))
    return candidates[0] if candidates else None


def main() -> int:
    parser = argparse.ArgumentParser(description="校验手势映射与模型类别是否一致")
    parser.add_argument("--model", type=Path, help="权重文件路径，默认取 models/ 下第一个 .pt")
    args = parser.parse_args()

    if not MAP_PATH.exists():
        print(f"[x] 找不到配置文件：{MAP_PATH}")
        return 2

    cfg = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    gestures = cfg.get("gestures", [])
    if not gestures:
        print("[x] 配置里没有 gestures 列表")
        return 2

    print(f"[配置] {MAP_PATH.relative_to(ROOT)}  共 {len(gestures)} 个手势")

    # ---- 1. 结构校验 ----
    errors: list[str] = []
    seen_ids: set[str] = set()
    for g in gestures:
        gid = g.get("id", "<无 id>")
        if gid in seen_ids:
            errors.append(f"手势 id 重复：{gid}")
        seen_ids.add(gid)
        if g.get("action") not in ALLOWED_ACTIONS:
            errors.append(f"{gid} 的 action 非法：{g.get('action')}")
        if not g.get("model_class"):
            errors.append(f"{gid} 缺少 model_class")

    # ---- 2. 与模型对照 ----
    model_path = args.model or find_default_model()
    classes: list[str] = []
    if model_path and model_path.exists():
        try:
            classes = read_model_classes(model_path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"读取权重失败：{exc}")
        print(f"[模型] {model_path.name}  共 {len(classes)} 个类别")
    else:
        print("[模型] 未找到权重文件，仅做结构校验（先跑 scripts/download_model.py）")

    print()
    print(f"{'手势':<12}{'类别':<16}{'动作':<22}{'检出情况'}")
    print("-" * 66)
    missing: list[str] = []
    for g in gestures:
        cls = g.get("model_class", "")
        status = "—"
        if classes:
            if cls in classes:
                status = "OK"
            else:
                fb = [c for c in g.get("fallbacks", []) if c in classes]
                status = f"缺类别，可用备选 {fb}" if fb else "缺类别"
                missing.append(f"{g.get('label')}({cls})")
        print(f"{g.get('label', ''):<12}{cls:<16}{g.get('action', ''):<22}{status}")

    if errors:
        print("\n[结构问题]")
        for e in errors:
            print(f"  - {e}")

    if missing:
        print("\n[需要处理] 以下手势在当前权重中没有对应类别：")
        for m in missing:
            print(f"  - {m}")
        print("  → 要么改 model_class 指向已有类别，要么自采样本微调补类")

    if errors or missing:
        return 1
    print("\n全部手势与模型类别匹配。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

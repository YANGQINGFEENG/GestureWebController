"""配置加载：模型参数（model.yaml）与手势映射（gesture_map.json）。

约定：
- 类别名只出现在 config/gesture_map.json，代码里不硬编码（AGENTS.md 硬性约定 2）。
- 本模块只读配置，不依赖 torch / ultralytics。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = ROOT / "config"
MODEL_CONFIG_PATH = CONFIG_DIR / "model.yaml"
GESTURE_MAP_PATH = CONFIG_DIR / "gesture_map.json"


@dataclass(frozen=True)
class ModelConfig:
    path: Path
    imgsz: int = 640
    conf: float = 0.7
    iou: float = 0.45
    max_det: int = 4
    device: str = "cpu"


@dataclass(frozen=True)
class Gesture:
    """一个手势的完整定义。id 是语义标识，model_class 是当前权重里的类别名。"""

    id: str
    label: str
    model_class: str
    action: str
    action_label: str = ""
    emoji: str = ""
    desc: str = ""
    fallbacks: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Gesture":
        return cls(
            id=str(data["id"]),
            label=str(data.get("label") or data["id"]),
            model_class=str(data["model_class"]),
            action=str(data["action"]),
            action_label=str(data.get("action_label", "")),
            emoji=str(data.get("emoji", "")),
            desc=str(data.get("desc", "")),
            fallbacks=tuple(str(x) for x in (data.get("fallbacks") or ())),
        )


@dataclass(frozen=True)
class GestureMap:
    gestures: tuple[Gesture, ...]
    debounce: dict[str, Any]
    ignored_classes: frozenset[str]
    _index: dict[str, Gesture] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        index: dict[str, Gesture] = {}
        for gesture in self.gestures:
            for class_name in (gesture.model_class, *gesture.fallbacks):
                index.setdefault(class_name, gesture)
        object.__setattr__(self, "_index", index)

    def match(self, model_class: str) -> Gesture | None:
        """模型类别名 → 手势定义；未映射或属于忽略类（如 no_gesture）返回 None。"""
        if model_class in self.ignored_classes:
            return None
        return self._index.get(model_class)

    @property
    def model_classes(self) -> tuple[str, ...]:
        return tuple(self._index)


@lru_cache(maxsize=1)
def load_model_config() -> ModelConfig:
    raw = yaml.safe_load(MODEL_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    model = raw.get("model") or {}
    model_path = Path(str(model.get("path", "models/YOLOv10n_gestures.pt")))
    if not model_path.is_absolute():
        model_path = ROOT / model_path
    return ModelConfig(
        path=model_path,
        imgsz=int(model.get("imgsz", 640)),
        conf=float(model.get("conf", 0.7)),
        iou=float(model.get("iou", 0.45)),
        max_det=int(model.get("max_det", 4)),
        device=str(model.get("device", "cpu")),
    )


@lru_cache(maxsize=1)
def load_gesture_map() -> GestureMap:
    raw = json.loads(GESTURE_MAP_PATH.read_text(encoding="utf-8"))
    gestures = tuple(Gesture.from_dict(item) for item in raw.get("gestures", []))
    if not gestures:
        raise ValueError("config/gesture_map.json 里没有 gestures 定义")
    return GestureMap(
        gestures=gestures,
        debounce=dict(raw.get("debounce") or {}),
        ignored_classes=frozenset(raw.get("ignored_classes") or ()),
    )

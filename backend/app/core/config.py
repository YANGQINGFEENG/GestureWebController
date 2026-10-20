"""配置加载：模型参数（model.yaml）、手势映射（gesture_map.json）、应用配置（app.yaml）。

约定：
- 类别名只出现在 config/gesture_map.json，代码里不硬编码（AGENTS.md 硬性约定 2）。
- 本模块只读配置，不依赖 torch / ultralytics / sqlalchemy。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = ROOT / "config"
MODEL_CONFIG_PATH = CONFIG_DIR / "model.yaml"
GESTURE_MAP_PATH = CONFIG_DIR / "gesture_map.json"
APP_CONFIG_PATH = CONFIG_DIR / "app.yaml"


@dataclass(frozen=True)
class ModelConfig:
    path: Path
    imgsz: int = 640
    conf: float = 0.7
    candidate_conf: float = 0.3
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
    min_conf: float = 0.0  # >0 时覆盖 model.yaml 的 conf，用于近似映射的手势

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
            min_conf=float(data.get("min_conf") or 0.0),
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


@dataclass(frozen=True)
class DatabaseConfig:
    url: str = "sqlite:///data/app.db"
    echo: bool = False
    enabled: bool = True
    create_tables: bool = True

    @property
    def is_sqlite(self) -> bool:
        return self.url.startswith("sqlite")


@dataclass(frozen=True)
class AuthConfig:
    secret: str = ""
    algorithm: str = "HS256"
    expire_hours: int = 168
    min_password_length: int = 6
    allow_register: bool = True


@dataclass(frozen=True)
class RecordConfig:
    enabled: bool = True
    max_per_user: int = 0


@dataclass(frozen=True)
class UploadConfig:
    """图片识别的落盘策略。图片只存磁盘，库里记相对路径（ADR-014）。"""

    enabled: bool = True
    dir: Path = ROOT / "data" / "uploads"
    max_side: int = 1280
    jpeg_quality: int = 82
    max_bytes: int = 8 * 1024 * 1024
    keep_days: int = 0

    @property
    def url_prefix(self) -> str:
        """对外访问前缀，与 main.py 里挂载的 /media/uploads 对应。"""
        return "/media/uploads"


@dataclass(frozen=True)
class AppConfig:
    database: DatabaseConfig
    auth: AuthConfig
    records: RecordConfig
    upload: UploadConfig


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _absolutize(url: str) -> str:
    """把 sqlite:///data/app.db 这类相对路径解析到仓库根目录，避免受启动目录影响。"""
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return url
    raw_path = url[len(prefix) :]
    if raw_path.startswith(":memory:") or Path(raw_path).is_absolute():
        return url
    return f"{prefix}{(ROOT / raw_path).as_posix()}"


@lru_cache(maxsize=1)
def load_app_config() -> AppConfig:
    raw: dict[str, Any] = {}
    if APP_CONFIG_PATH.exists():
        raw = yaml.safe_load(APP_CONFIG_PATH.read_text(encoding="utf-8")) or {}

    db = raw.get("database") or {}
    auth = raw.get("auth") or {}
    records = raw.get("records") or {}
    upload = raw.get("upload") or {}

    upload_dir = Path(
        os.getenv("GWC_UPLOAD_DIR") or str(upload.get("dir", "data/uploads"))
    )
    if not upload_dir.is_absolute():
        upload_dir = ROOT / upload_dir

    return AppConfig(
        database=DatabaseConfig(
            url=_absolutize(os.getenv("GWC_DB_URL") or str(db.get("url", "sqlite:///data/app.db"))),
            echo=_env_bool("GWC_DB_ECHO", bool(db.get("echo", False))),
            enabled=_env_bool("GWC_DB_ENABLED", bool(db.get("enabled", True))),
            create_tables=bool(db.get("create_tables", True)),
        ),
        auth=AuthConfig(
            secret=os.getenv("GWC_JWT_SECRET") or str(auth.get("secret") or ""),
            algorithm=str(auth.get("algorithm", "HS256")),
            expire_hours=int(auth.get("expire_hours", 168)),
            min_password_length=int(auth.get("min_password_length", 6)),
            allow_register=_env_bool("GWC_ALLOW_REGISTER", bool(auth.get("allow_register", True))),
        ),
        records=RecordConfig(
            enabled=_env_bool("GWC_RECORDS_ENABLED", bool(records.get("enabled", True))),
            max_per_user=int(records.get("max_per_user", 0)),
        ),
        upload=UploadConfig(
            enabled=_env_bool("GWC_UPLOAD_ENABLED", bool(upload.get("enabled", True))),
            dir=upload_dir,
            max_side=int(upload.get("max_side", 1280)),
            jpeg_quality=int(upload.get("jpeg_quality", 82)),
            max_bytes=int(upload.get("max_bytes", 8 * 1024 * 1024)),
            keep_days=int(upload.get("keep_days", 0)),
        ),
    )


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
        candidate_conf=float(model.get("candidate_conf", 0.3)),
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

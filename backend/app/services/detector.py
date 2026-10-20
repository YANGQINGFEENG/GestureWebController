"""YOLO 手势检测封装。

**全项目唯一 import ultralytics 的地方**（AGENTS.md 硬性约定 5），其余层只认本模块返回的字典。

职责边界：
- 输入：一张图片的字节流
- 输出：已映射为手势的检测结果（含语义 id / 动作 / 置信度 / 框坐标）+ 推理耗时
- 不做防抖、不落库、不认用户（那些属于 SDK 与业务层）
"""

from __future__ import annotations

import io
import logging
import time
from typing import Any

import numpy as np
from PIL import Image, ImageOps

from backend.app.core.config import (
    GestureMap,
    ModelConfig,
    load_gesture_map,
    load_model_config,
)

logger = logging.getLogger(__name__)


class ModelNotFoundError(RuntimeError):
    """权重文件缺失。"""


class InvalidImageError(ValueError):
    """上传内容不是可解析的图片。"""


def decode_image(data: bytes) -> np.ndarray:
    """字节流 → RGB ndarray，按 EXIF 方向自动摆正（手机竖拍照片必需）。"""
    try:
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")
    except Exception as exc:  # noqa: BLE001
        # 详细原因只进日志，对外统一口径，避免把内部依赖名暴露给前端
        logger.warning("图片解析失败：%s", exc)
        raise InvalidImageError("无法解析图片，请上传 JPEG / PNG 格式") from exc
    return np.asarray(image)


class GestureDetector:
    """线程内复用的推理器；模型懒加载，首次调用才占内存。"""

    def __init__(
        self,
        model_cfg: ModelConfig | None = None,
        gesture_map: GestureMap | None = None,
    ) -> None:
        self.model_cfg = model_cfg or load_model_config()
        self.gesture_map = gesture_map or load_gesture_map()
        self._model: Any = None
        self._names: dict[int, str] = {}

    # ---------- 生命周期 ----------

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self._model is not None:
            return
        path = self.model_cfg.path
        if not path.exists():
            raise ModelNotFoundError(
                f"权重文件不存在：{path}；请先运行 python scripts/download_model.py"
            )

        from ultralytics import YOLO  # 延迟导入，避免未装依赖时连配置都读不了

        started = time.perf_counter()
        logger.info("加载权重 %s", path)
        model = YOLO(str(path))
        self._names = {int(k): str(v) for k, v in (model.names or {}).items()}
        self._model = model
        self._warmup()
        logger.info(
            "模型就绪：%d 类，耗时 %.0f ms", len(self._names), (time.perf_counter() - started) * 1000
        )

    def _warmup(self) -> None:
        """空跑一次，避免首个真实请求承担初始化开销。"""
        blank = np.zeros((self.model_cfg.imgsz, self.model_cfg.imgsz, 3), dtype=np.uint8)
        self._infer(blank)

    # ---------- 推理 ----------

    def _infer(self, image: np.ndarray, conf: float | None = None, imgsz: int | None = None):
        cfg = self.model_cfg
        return self._model.predict(
            source=image,
            imgsz=int(imgsz or cfg.imgsz),
            conf=float(conf if conf is not None else cfg.candidate_conf),
            iou=cfg.iou,
            max_det=cfg.max_det,
            device=cfg.device,
            verbose=False,
        )

    def gate_for(self, gesture, override: float | None = None) -> float:
        """该手势的最低置信度：显式传参 > 手势的 min_conf > 全局默认。"""
        if override is not None:
            return override
        return gesture.min_conf if gesture.min_conf > 0 else self.model_cfg.conf

    def predict_bytes(
        self,
        data: bytes,
        conf: float | None = None,
        imgsz: int | None = None,
    ) -> dict[str, Any]:
        """单帧推理。返回 {gestures: [...], infer_ms, image_size}。

        两段式阈值：
        - `candidate_conf` 是送进 YOLO 的原始下限，只为拿到候选框（候选不一定算数）
        - 每个手势自己的门槛（min_conf / 全局 conf / 显式传参）才决定是否进结果
        这样近似映射的手势（如 🤟 借 rock 只有 0.5 左右）不会被全局阈值一刀切掉。
        """
        self.load()
        image = decode_image(data)
        height, width = image.shape[:2]

        raw_conf = self.model_cfg.candidate_conf if conf is None else min(
            self.model_cfg.candidate_conf, conf
        )
        started = time.perf_counter()
        results = self._infer(image, conf=raw_conf, imgsz=imgsz)
        infer_ms = (time.perf_counter() - started) * 1000

        best: dict[str, dict[str, Any]] = {}
        boxes = getattr(results[0], "boxes", None)
        if boxes is not None and len(boxes) > 0:
            classes = boxes.cls.tolist()
            confidences = boxes.conf.tolist()
            coords = boxes.xyxy.tolist()
            for cls_id, score, xyxy in zip(classes, confidences, coords):
                model_class = self._names.get(int(cls_id), str(int(cls_id)))
                gesture = self.gesture_map.match(model_class)
                if gesture is None:
                    continue  # no_gesture 或未映射类别，直接丢弃
                score = float(score)
                if score < self.gate_for(gesture, conf):
                    continue  # 低于该手势自己的门槛
                item = {
                    "class": model_class,
                    "id": gesture.id,
                    "label": gesture.label,
                    "emoji": gesture.emoji,
                    "action": gesture.action,
                    "action_label": gesture.action_label,
                    "conf": round(score, 4),
                    "box": [round(float(v), 1) for v in xyxy],
                }
                # 同一手势多只手时只留最高分，避免一次动作触发两次
                current = best.get(gesture.id)
                if current is None or item["conf"] > current["conf"]:
                    best[gesture.id] = item

        gestures = sorted(best.values(), key=lambda g: g["conf"], reverse=True)
        return {
            "gestures": gestures,
            "infer_ms": round(infer_ms, 1),
            "image_size": [width, height],
        }

    # ---------- 自描述 ----------

    def info(self) -> dict[str, Any]:
        cfg = self.model_cfg
        return {
            "model": cfg.path.name,
            "model_exists": cfg.path.exists(),
            "model_loaded": self.loaded,
            "imgsz": cfg.imgsz,
            "conf": cfg.conf,
            "candidate_conf": cfg.candidate_conf,
            "device": cfg.device,
            "classes": len(self._names) if self.loaded else None,
            "gestures": [
                {
                    "id": g.id,
                    "label": g.label,
                    "model_class": g.model_class,
                    "action": g.action,
                    "min_conf": self.gate_for(g),
                }
                for g in self.gesture_map.gestures
            ],
            "debounce": self.gesture_map.debounce,
        }

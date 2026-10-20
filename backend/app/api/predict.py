"""手势识别接口：/api/health、/api/predict。

契约见 docs/技术选型与开发计划.md 第六节。
本模块只做 HTTP 层的事：校验入参、转线程池推理、包装错误；不含任何模型逻辑。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from backend.app.api.common import FRAME_MAX_BYTES, check_conf, check_imgsz, read_image_upload
from backend.app.services.detector import (
    GestureDetector,
    InvalidImageError,
    ModelNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["gesture"])

_detector: GestureDetector | None = None


def get_detector() -> GestureDetector:
    global _detector
    if _detector is None:
        _detector = GestureDetector()
    return _detector


@router.get("/health", summary="健康检查与模型自描述")
async def health() -> dict:
    """不触发模型加载，用于前端探测服务是否就绪。"""
    return {"ok": True, **get_detector().info()}


@router.post("/predict", summary="单帧手势识别")
async def predict(
    frame: UploadFile = File(..., description="JPEG/PNG 图像二进制"),
    conf: float | None = Form(None, description="置信度阈值，覆盖配置默认值"),
    imgsz: int | None = Form(None, description="推理分辨率，覆盖配置默认值"),
) -> dict:
    data = await read_image_upload(frame, max_bytes=FRAME_MAX_BYTES, field="图片")
    check_conf(conf)
    check_imgsz(imgsz)

    detector = get_detector()
    try:
        result = await run_in_threadpool(detector.predict_bytes, data, conf, imgsz)
    except ModelNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except InvalidImageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("推理失败")
        raise HTTPException(status_code=500, detail=f"推理失败：{exc}") from exc

    return {"ok": True, **result}

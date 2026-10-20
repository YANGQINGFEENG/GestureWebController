"""图片识别接口：`POST /api/image/recognize`（M3 三条链路的共同后端）。

三条链路只是「图从哪来」不同，后端完全一样，用 `source` 区分入库来源：

| 链路 | source | 触发方式 |
| --- | --- | --- |
| ① 手动上传图片 | `upload` | 用户选文件 |
| ② 🤞 手势触发图片识别 | `gesture` | 手势唤起上传后自动提交 |
| ③ 🤟/🖐️ 截屏后 AI 搜索 | `screenshot` | html2canvas 截图自动上传 |

契约（docs/技术选型与开发计划.md 第六节）：

    POST /api/image/recognize
    multipart/form-data: image=<file> source=upload|gesture|screenshot conf? imgsz?
    → 200 {
        ok, result, label, gestures[], raw_count, image_size,
        img_path, img_url, record, saved, timings
      }

与 `/api/predict` 的区别：那个是视频流的一帧，无状态、不落盘、不写库（防抖在前端）；
这个是用户主动的一次「识别」动作，要留痕——原图落盘可回看，结果写 `image_record`。
"""

from __future__ import annotations

import logging
import time
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from backend.app.api.common import check_conf, check_imgsz, read_image_upload
from backend.app.api.deps import MaybeDb, OptionalUser
from backend.app.api.predict import get_detector
from backend.app.core.config import load_app_config
from backend.app.db import repository
from backend.app.db.session import db_unavailable_reason
from backend.app.services import describe as describe_svc
from backend.app.services import storage
from backend.app.services.detector import InvalidImageError, ModelNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/image", tags=["image"])

ImageSource = Literal["upload", "gesture", "screenshot"]


@router.post("/recognize", summary="图片识别（上传 / 手势触发 / 截屏）")
async def recognize(
    user: OptionalUser,
    db: MaybeDb,
    image: UploadFile = File(..., description="待识别图片二进制"),
    source: Annotated[ImageSource, Form(description="来源：upload / gesture / screenshot")] = "upload",
    conf: float | None = Form(None, description="置信度阈值，覆盖配置默认值"),
    imgsz: int | None = Form(None, description="推理分辨率，覆盖配置默认值"),
) -> dict:
    started = time.perf_counter()
    cfg = load_app_config()
    data = await read_image_upload(image, max_bytes=cfg.upload.max_bytes, field="图片")
    check_conf(conf)
    check_imgsz(imgsz)

    detector = get_detector()
    try:
        detected = await run_in_threadpool(detector.predict_bytes, data, conf, imgsz)
    except ModelNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except InvalidImageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("图片识别推理失败")
        raise HTTPException(status_code=500, detail=f"识别失败：{exc}") from exc

    gestures = detected["gestures"]
    result_text, label = describe_svc.describe(
        gestures, raw_count=detected.get("raw_count", 0), image_size=detected["image_size"]
    )

    # 落盘失败不影响识别：img_path 留空，前端只是少一个预览图
    saved_image = await run_in_threadpool(storage.save_image, data)
    img_path = saved_image.rel_path if saved_image else ""

    payload = {
        "ok": True,
        "result": result_text,
        "label": label,
        "gestures": gestures,
        "raw_count": detected.get("raw_count", 0),
        "image_size": detected["image_size"],
        "img_path": img_path,
        "img_url": saved_image.url if saved_image else None,
        "image": saved_image.to_dict() if saved_image else None,
        "saved": False,
        "record": None,
        "source": source,
    }

    if db is None or not cfg.records.enabled:
        payload["reason"] = (
            "记录功能已在配置中关闭" if db is not None else (db_unavailable_reason() or "数据库不可用")
        )
    else:
        try:
            record = repository.add_image_record(
                db,
                uid=user.uid if user else None,
                img_path=img_path,
                result=result_text,
                label=label,
                source=source,
                confidence=float(gestures[0]["conf"]) if gestures else 0.0,
            )
        except SQLAlchemyError as exc:
            # 与手势上报同一原则（ADR-006）：记录是可插拔日志层，写不进去也要给用户结果
            logger.warning("图片识别记录落库失败（不影响识别结果）：%s", exc)
            db.rollback()
            payload["reason"] = "数据库写入失败"
        else:
            payload["saved"] = True
            payload["record"] = record.to_dict()

    payload["timings"] = {
        "infer_ms": detected["infer_ms"],
        "save_ms": round(saved_image.save_ms, 1) if saved_image else 0.0,
        "total_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    return payload

"""图片上传接口的公共校验。

`/api/predict`（视频帧）与 `/api/image/recognize`（整张图片）的校验规则几乎一样，
唯一区别是体积上限：帧是前端压过的 200KB 级，图片可能是手机原图。
抽在这里，避免两处各写一份、改一个忘一个。
"""

from __future__ import annotations

from fastapi import HTTPException, UploadFile

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/bmp"}

FRAME_MAX_BYTES = 4 * 1024 * 1024  # 单帧上限 4MB


async def read_image_upload(
    file: UploadFile, *, max_bytes: int, field: str = "图片"
) -> bytes:
    """校验类型与体积并读出字节流，任何不合规都抛 415 / 400 / 413。"""
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"不支持的{field}类型：{file.content_type or '未知'}；"
            f"支持 JPEG / PNG / WebP / BMP",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail=f"{field}内容为空")
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"{field}过大（{len(data) / 1048576:.1f}MB），上限 {max_bytes / 1048576:.0f}MB",
        )
    return data


def check_conf(conf: float | None) -> None:
    if conf is not None and not 0.0 < conf <= 1.0:
        raise HTTPException(status_code=422, detail="conf 需在 (0, 1] 之间")


def check_imgsz(imgsz: int | None) -> None:
    if imgsz is not None and not 160 <= imgsz <= 1280:
        raise HTTPException(status_code=422, detail="imgsz 需在 160~1280 之间")

"""上传图片落盘：图片识别的原图要能回看，但绝不以二进制塞进数据库。

设计取舍（ADR-014）：
- 库里只存**相对路径**（`2026-10/xxxx.jpg`），换机器、换部署目录都不用改数据；
- 文件名用 uuid4，不带用户输入，天然免疫路径穿越与中文文件名乱码；
- 落盘前统一 EXIF 摆正 + 转 RGB + 长边压到 `max_side`，手机原图 5MB 进来约 150KB 出去；
- 目录按月分片，避免单目录几万个文件拖慢文件系统；
- 目录不在 `data/` 根下直接挂静态服务，只挂 `data/uploads`，防止 `app.db`、`.jwt_secret` 被下载。

职责边界：只负责「字节流 → 磁盘文件 + 可访问路径」，不做识别、不写数据库。
"""

from __future__ import annotations

import io
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from PIL import Image, ImageOps

from backend.app.core.config import UploadConfig, load_app_config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SavedImage:
    """一张已落盘的图片。`rel_path` 用于入库，`url` 直接给 <img src>。"""

    rel_path: str
    url: str
    width: int
    height: int
    bytes: int
    save_ms: float

    def to_dict(self) -> dict:
        return {
            "rel_path": self.rel_path,
            "url": self.url,
            "width": self.width,
            "height": self.height,
            "bytes": self.bytes,
            "save_ms": round(self.save_ms, 1),
        }


def _fit(image: Image.Image, max_side: int) -> Image.Image:
    """等比缩到长边不超过 max_side；本来就小的图不放大。"""
    width, height = image.size
    longest = max(width, height)
    if longest <= max_side:
        return image
    scale = max_side / longest
    return image.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.LANCZOS)


def save_image(data: bytes, *, cfg: UploadConfig | None = None) -> SavedImage | None:
    """保存一张上传图。关闭落盘或写入失败时返回 None，调用方按「没有回看地址」处理。

    失败绝不抛异常：图片识别的结果已经算出来了，不能因为磁盘满了就让用户看不到结果。
    """
    cfg = cfg or load_app_config().upload
    if not cfg.enabled:
        return None

    started = time.perf_counter()
    try:
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")
        image = _fit(image, cfg.max_side)

        month = datetime.now(UTC).strftime("%Y-%m")
        target_dir = cfg.dir / month
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4().hex}.jpg"
        target = target_dir / filename
        image.save(target, format="JPEG", quality=cfg.jpeg_quality, optimize=True)

        rel_path = f"{month}/{filename}"
        return SavedImage(
            rel_path=rel_path,
            url=f"{cfg.url_prefix}/{rel_path}",
            width=image.width,
            height=image.height,
            bytes=target.stat().st_size,
            save_ms=(time.perf_counter() - started) * 1000,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("图片落盘失败（不影响识别结果返回）：%s", exc)
        return None


def prune_old_files(cfg: UploadConfig | None = None) -> int:
    """删除 keep_days 天前的旧图，返回删除数量。启动时跑一次，失败只记日志。"""
    cfg = cfg or load_app_config().upload
    if cfg.keep_days <= 0 or not cfg.dir.exists():
        return 0

    cutoff = datetime.now(UTC) - timedelta(days=cfg.keep_days)
    removed = 0
    for path in cfg.dir.rglob("*.jpg"):
        try:
            if datetime.fromtimestamp(path.stat().st_mtime, UTC) < cutoff:
                path.unlink()
                removed += 1
        except OSError as exc:
            logger.debug("清理旧图失败 %s：%s", path, exc)
    if removed:
        logger.info("已清理 %d 张超过 %d 天的旧图", removed, cfg.keep_days)
    # 顺手删掉空月份目录，别留一堆空壳
    for folder in sorted(cfg.dir.glob("*"), reverse=True):
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    return removed


def resolve_rel_path(rel_path: str, cfg: UploadConfig | None = None) -> Path | None:
    """把入库的相对路径还原成磁盘路径；越界或不存在返回 None（防路径穿越）。"""
    if not rel_path:
        return None
    cfg = cfg or load_app_config().upload
    try:
        target = (cfg.dir / rel_path).resolve()
        target.relative_to(cfg.dir.resolve())
    except (ValueError, OSError):
        return None
    return target if target.exists() else None

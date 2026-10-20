"""GestureWebController 后端入口。

启动（仓库根目录）：
    .venv\\Scripts\\python.exe -m uvicorn backend.app.main:app --reload --port 8000
    或 .venv\\Scripts\\python.exe scripts/start_dev.py（同时起静态服务）

接口文档：http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from backend.app.api import admin, auth, predict, recognize, records, system
from backend.app.core.config import load_app_config
from backend.app.db import session as db_session
from backend.app.db.seed import ensure_admin
from backend.app.services import storage

logging.basicConfig(
    level=os.getenv("GWC_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="GestureWebController API",
    description="基于 YOLO 的手势识别服务：摄像头帧 → 手势 → 页面指令",
    version="0.2.0",
)

# 演示阶段允许任意来源（SDK 需嵌入第三方页面）；上线前应收敛为白名单
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(predict.router)
app.include_router(recognize.router)
app.include_router(auth.router)
app.include_router(records.router)
app.include_router(admin.router)
app.include_router(system.router)

# 识别用的图片单独挂载：只暴露 uploads 目录，data/app.db 与 .jwt_secret 不会被顺带下载（ADR-014）
if load_app_config().upload.enabled:
    _upload_dir = load_app_config().upload.dir
    _upload_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/media/uploads", StaticFiles(directory=_upload_dir), name="uploads")


@app.get("/", include_in_schema=False)
async def index() -> dict:
    return {
        "name": "GestureWebController API",
        "version": app.version,
        "docs": "/docs",
        "health": "/api/health",
        "status": "/api/system/status",
        "predict": "POST /api/predict",
        "recognize": "POST /api/image/recognize",
        "auth": ["POST /api/auth/register", "POST /api/auth/login", "GET /api/auth/me"],
        "records": "GET/POST /api/records/gesture",
    }


@app.on_event("startup")
async def on_startup() -> None:
    """数据库初始化 + 可选模型预加载。任何一步失败都只降级，不阻止服务启动。"""
    cfg = load_app_config()

    if cfg.database.enabled:
        if db_session.init_db():
            ensure_admin()
        db_status = "可用" if db_session.db_available() else "不可用"
        logger.info("数据库状态：%s（记录功能%s）", db_status, "开启" if cfg.records.enabled else "关闭")
    else:
        logger.info("数据库已在配置中关闭：手势操控正常，记录不落库")

    try:
        storage.prune_old_files()
    except Exception as exc:  # noqa: BLE001
        logger.warning("清理旧图片失败（不影响服务）：%s", exc)

    if os.getenv("GWC_PRELOAD") != "1":
        return
    detector = predict.get_detector()
    try:
        await run_in_threadpool(detector.load)
        logger.info("模型已预加载")
    except Exception as exc:  # noqa: BLE001
        logger.warning("预加载模型失败（接口仍可用，首次请求再试）：%s", exc)

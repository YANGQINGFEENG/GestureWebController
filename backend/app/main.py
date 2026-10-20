"""GestureWebController 后端入口。

启动（仓库根目录）：
    .venv\\Scripts\\python.exe -m uvicorn backend.app.main:app --reload --port 8000

接口文档：http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from backend.app.api import predict

logging.basicConfig(
    level=os.getenv("GWC_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI(
    title="GestureWebController API",
    description="基于 YOLO 的手势识别服务：摄像头帧 → 手势 → 页面指令",
    version="0.1.0",
)

# 演示阶段允许任意来源（SDK 需嵌入第三方页面）；上线前应收敛为白名单
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(predict.router)


@app.get("/", include_in_schema=False)
async def index() -> dict:
    return {
        "name": "GestureWebController API",
        "version": app.version,
        "docs": "/docs",
        "health": "/api/health",
        "predict": "POST /api/predict",
    }


@app.on_event("startup")
async def preload_model() -> None:
    """设置 GWC_PRELOAD=1 时启动即加载模型，避免首帧请求卡顿。"""
    if os.getenv("GWC_PRELOAD") != "1":
        return
    detector = predict.get_detector()
    try:
        await run_in_threadpool(detector.load)
        logging.getLogger(__name__).info("模型已预加载")
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).warning("预加载模型失败（接口仍可用，首次请求再试）：%s", exc)

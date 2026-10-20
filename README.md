# GestureWebController

> 基于 YOLOv8 手势识别的 Web 智能演示控制系统 —— 一套可嵌入任意网页的**手势控制 SDK**。

前端采集摄像头视频流，后端用 YOLO 预训练权重做手势检测，识别结果映射为网页交互指令（上翻 / 下翻 / 截屏 / 确定 / 触发图片识别 / 截屏 + AI 搜索），由前端 JS 直接操控当前页面。工具解耦设计，业务页面只需引入一个脚本即可接入。

---

## 核心能力

| 手势 | 动作 | 说明 |
| ---- | ---- | ---- |
| ✌️ | 下翻页 | 页面向下滚动 / 下一屏 |
| ☝️ | 上翻页 | 页面向上滚动 / 上一屏 |
| 🖐️ | 截屏 | 抓取当前网页可视区域 |
| 👍 | 确定 | 模拟点击焦点元素 |
| 🤞 | 触发图片识别 | 唤起图片上传，后端识别图片内容 |
| 🤟 | 截屏 + AI 搜索 | 自动截屏 → 上传 → 识别 → 结果回显 |

**防抖机制**：连续 3 帧识别到同一手势且置信度 ≥ 0.7 才触发动作，避免抖动误触发。
手势与动作的映射写在 `config/gesture_map.json`，改配置即可，无需改动推理核心代码。

---

## 技术栈

| 模块 | 技术 |
| ---- | ---- |
| 手势检测 | YOLOv8（Ultralytics）+ 开源手势预训练权重 |
| 后端服务 | Python / FastAPI，独立 API 服务，可单独启动 |
| 前端 SDK | 原生 JS，摄像头采集 + Canvas 绘制 + html2canvas 截屏 |
| 数据库 | 关系型数据库，4 张表（user / gesture_record / image_record / chat_record） |
| AI 问答 | 大语言模型 API，支持图文联动提问 |

---

## 目录结构

```
GestureWebController/
├── backend/                 # 后端推理服务（FastAPI）
│   └── app/
│       ├── api/             # 路由：predict / image / chat / record / admin
│       ├── services/        # YOLO 推理、图像识别、AI 问答、日志上报
│       ├── db/              # ORM 模型、会话、初始化脚本
│       └── core/            # 配置、鉴权、依赖注入
├── frontend/                # 业务站点页面
│   ├── pages/               # 首页 / 登录 / 演示主页 / AI 问答 / 个人中心 / 后台
│   └── assets/              # 样式、图标、静态资源
├── sdk/                     # 可复用前端 SDK（构建产物放 dist/）
├── models/                  # 模型权重存放目录（权重不入库）
├── config/                  # 手势映射等配置文件
├── scripts/                 # 一键启动、数据初始化等脚本
├── data/                    # 运行期数据：数据库、上传图片、截图
└── docs/                    # 需求文档与设计文档
```

详细需求见 [docs/GestureWebController需求文档.md](docs/GestureWebController需求文档.md)。

---

## 快速接入（设计目标 API）

```js
const gestureCtrl = new GestureWebController({
  apiUrl: "http://127.0.0.1:8000/predict",
  enableVisual: true,
  debounceFrame: 3,
  confThreshold: 0.7,
  enableImageRec: true,
  enableScreenshotSearch: true
});
gestureCtrl.start();

gestureCtrl.on("gestureTrigger", (name) => console.log("触发手势：", name));
gestureCtrl.on("screenshotSearchDone", (res) => console.log("截图识别：", res.result));
gestureCtrl.on("imageRecDone", (res) => console.log("图片识别：", res.result));
```

---

## 本地运行

> 环境搭建与启动步骤在首个可运行版本完成后补齐，当前仓库为工程骨架。

---

## 开源来源与致谢

本项目基于 GitHub 公开的 YOLO 手势识别仓库二次开发，复用其预训练权重与检测推理代码，在 Web 端封装为可复用的手势控制 SDK：

- [ultralytics/ultralytics](https://github.com/ultralytics/ultralytics) —— YOLOv8 官方框架，AGPL-3.0
- YOLOv8 Hand Gesture Detection 类开源手势检测仓库（具体仓库与协议随权重引入时在 `docs/` 补充登记）

使用时请遵守上游项目开源协议。

---

## 分支约定

- `main`：稳定可演示版本
- `dev`：日常开发分支，功能完成后合入 `main`

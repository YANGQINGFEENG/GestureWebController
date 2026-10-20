# GestureWebController

> 基于 YOLOv8 手势识别的 Web 智能演示控制系统 —— 一套可嵌入任意网页的**手势控制 SDK**。

前端采集摄像头视频流，后端用 YOLO 预训练权重做手势检测，识别结果映射为网页交互指令（上翻 / 下翻 / 截屏 / 确定 / 触发图片识别 / 截屏 + AI 搜索），由前端 JS 直接操控当前页面。工具解耦设计，业务页面只需引入一个脚本即可接入。

## 先看这里（换电脑 / 换 AI 接手）

| 我想… | 打开 |
| --- | --- |
| 知道现在做到哪一步 | [`docs/开发进度.md`](docs/开发进度.md) —— front matter 就是当前状态 |
| 在新电脑上跑起来 | [`docs/交接说明.md`](docs/交接说明.md) |
| 了解为什么这样设计 | [`docs/决策记录.md`](docs/决策记录.md)（ADR） |
| 看最近谁改了什么 | [`docs/开发日志.md`](docs/开发日志.md) |
| 让 AI 助手接手 | [`AGENTS.md`](AGENTS.md) |
| 完整需求与计划 | [`docs/GestureWebController需求文档.md`](docs/GestureWebController需求文档.md)、[`docs/技术选型与开发计划.md`](docs/技术选型与开发计划.md) |

> 跑起来三连：`python scripts/download_model.py` → `sh scripts/install_hooks.sh` → `python scripts/check_gesture_map.py`


---

## 核心能力

| 手势 | 名称 | 模型类别 | 动作 | 说明 |
| ---- | ---- | ---- | ---- | ---- |
| ✌️ | V 手势 | `peace` | 下翻页 | 页面向下滚动 / 下一屏 |
| ☝️ | 食指上指 | `point` | 上翻页 | 页面向上滚动 / 上一屏 |
| 🖐️ | 张开手掌 | `palm` | 截屏 | 抓取当前网页可视区域 |
| 👍 | 点赞 | `like` | 确定 | 模拟点击焦点元素 |
| 🤞 | 交叉手指 | `xsign` | 触发图片识别 | 唤起图片上传，后端识别图片内容 |
| 🤟 | 爱与和平 | `rock`（近似映射） | 截屏 + AI 搜索 | 自动截屏 → 上传 → 识别 → 结果回显 |

> 前 5 个类别与 HaGRIDv2 预训练权重精确对应；🤟 在模型中没有对应类别，暂用姿态最接近的 `rock`(🤘) 映射，后续通过增类微调补齐。

改手势或改动作只需编辑 `config/gesture_map.json`（`id` 是语义标识、`model_class` 是模型类别名，两者分离），改完跑一次自检确认配置和模型对得上：

```bash
python scripts/check_gesture_map.py
```


**防抖机制**：连续 3 帧识别到同一手势且置信度 ≥ 0.7 才触发动作，避免抖动误触发。
手势与动作的映射写在 `config/gesture_map.json`，改配置即可，无需改动推理核心代码。

---

## 技术栈

| 模块 | 技术 |
| ---- | ---- |
| 手势检测 | Ultralytics YOLO + HaGRIDv2 预训练权重（34 类，默认 YOLOv10n，可换 YOLOv8n 自定义权重） |
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

本项目建立在以下开源工作之上，复用其模型、权重与设计经验，Web 全栈部分为自研：

| 项目 | 协议 | 本项目复用的部分 |
| --- | --- | --- |
| [hukenovs/hagrid](https://github.com/hukenovs/hagrid)（HaGRIDv2） | CC BY-SA 4.0 | 手势检测**预训练权重**（34 类），及可用于增类微调的标注数据 |
| [ultralytics/ultralytics](https://github.com/ultralytics/ultralytics) | AGPL-3.0 | YOLO 训练 / 推理 / 模型导出框架 |
| [Kazuhito00/hand-gesture-recognition-using-mediapipe](https://github.com/Kazuhito00/hand-gesture-recognition-using-mediapipe) | Apache-2.0 | 手势判定、点历史平滑、防抖与 Web demo 的**设计参考**（未复制代码） |

模型权重体积较大，不入库，通过 `scripts/download_model.py` 拉取；衍生权重同样以 CC BY-SA 4.0 方式共享。

技术选型依据、6 种手势与模型类别的映射核对、分阶段里程碑见 [docs/技术选型与开发计划.md](docs/技术选型与开发计划.md)。


---

## 分支约定

- `main`：稳定可演示版本
- `dev`：日常开发分支，功能完成后合入 `main`

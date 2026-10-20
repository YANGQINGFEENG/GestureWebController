# GestureWebController

> 基于 YOLO 手势识别（YOLOv10n + HaGRIDv2 34 类权重）的 Web 智能演示控制系统 —— 一套可嵌入任意网页的**手势控制 SDK**。

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

> **跑起来只要一条命令**：
>
> - Windows：双击 `start.bat`（或在终端执行 `start.bat`）
> - macOS / Linux：`./start.sh`
>
> 它会自动建虚拟环境、装依赖、下权重、自检配置，最后同时起后端（8000）与演示页（8080）。
> 想先看看环境齐不齐：`start.bat --check`（不启动服务，只打印结论）。


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


**防抖机制**：连续 3 帧识别到同一手势、且置信度达到**该手势自己的门槛**才触发动作（默认 0.7，🤟 因借类映射放宽到 0.45），并带按手势计算的冷却时间，避免抖动误触发。
手势与动作的映射写在 `config/gesture_map.json`，改配置即可，无需改动推理核心代码。

---

## 技术栈

| 模块 | 技术 |
| ---- | ---- |
| 手势检测 | Ultralytics YOLO + HaGRIDv2 预训练权重（34 类，默认 YOLOv10n，可换 YOLOv8n 自定义权重） |
| 后端服务 | Python / FastAPI，独立 API 服务，可单独启动 |
| 前端 SDK | 原生 JS，摄像头采集 + Canvas 绘制 + html2canvas 截屏 |
| 数据库 | SQLite + SQLAlchemy 2.0，4 张表（user / gesture_record / image_record / chat_record），外键关联 |
| 账号鉴权 | bcrypt 密码哈希 + JWT，普通用户 / 管理员两种角色 |
| AI 问答 | 大语言模型 API，支持图文联动提问 |

---

## 目录结构

```
GestureWebController/
├── backend/                 # 后端推理服务（FastAPI）
│   └── app/
│       ├── api/             # 路由：predict / recognize / chat / auth / records / admin / system
│       ├── services/        # YOLO 推理（唯一 import ultralytics 的地方）/ 图片落盘 / 结果文案 / LLM
│       ├── db/              # 四张表的 ORM 模型、会话、数据访问、种子数据
│       └── core/            # 配置加载、密码哈希与 JWT
├── frontend/                # 业务站点页面
│   ├── pages/               # 演示主页 / 个人中心 / 后台管理 / 嵌入示例 / 截屏自检
│   └── assets/              # 登录态与接口封装（auth.js）
├── sdk/                     # 可复用前端 SDK（构建产物放 dist/）
├── models/                  # 模型权重存放目录（权重不入库）
├── config/                  # 手势映射（gesture_map.json）、模型参数、应用配置（app.yaml）
├── start.bat / start.sh     # 一键入口：自举环境 + 起服务（逻辑在 scripts/bootstrap.py）
├── scripts/                 # 自举、启动、下载权重、批量测试、接口与页面自检
├── data/                    # 运行期数据：数据库、上传图片、截图（全部不入库）
└── docs/                    # 需求文档、决策记录、进度看板、交接说明
```

详细需求见 [docs/GestureWebController需求文档.md](docs/GestureWebController需求文档.md)。

---

## 快速接入（9 行）

```html
<canvas id="cam" width="320" height="240"></canvas>

<script type="module">
  import { GestureWebController } from './sdk/src/index.js';

  const ctrl = new GestureWebController({
    canvas: document.querySelector('#cam'),
    endpoint: 'http://127.0.0.1:8000',
    fps: 8,
  });

  await ctrl.start();                                   // 默认开摄像头
  window.addEventListener('pagehide', () => ctrl.stop());
</script>
```

接完就能用：翻页 / 截屏 / 点击都由 SDK 的默认动作接管，业务页一行都不用写。
想看真实效果，打开 [`frontend/pages/embed-demo.html`](frontend/pages/embed-demo.html) —— 那是一个普通长文页，
除了上面这段代码没有任何本项目的东西。

需要定制时：

```js
// 1. 覆盖某个动作（其余仍用默认）
const ctrl = new GestureWebController({
  canvas,
  actions: { screenshot: ({ shot }) => uploadToMyServer(shot.blob) },
});

// 2. 只听事件，不动默认行为（拿不到 SDK 实例也能听）
ctrl.on('gestureTrigger', ({ gesture }) => console.log(gesture.id, gesture.action));
document.addEventListener('gestureweb:action', (e) => console.log(e.detail));
```

---

## 本地运行

最省事的方式（自动建环境、装依赖、下权重、自检、起服务）：

```bash
start.bat                 # Windows，双击也可以
./start.sh                # macOS / Linux
python scripts/bootstrap.py --check    # 只检查环境，不启动
```

想手动分步来（排查问题时更有用）：

```bash
# 1. 虚拟环境与依赖（清华镜像若拉不到 ultralytics，用 -i 指定官方源）
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -i https://pypi.org/simple -r backend/requirements.txt

# 2. 权重（22MB，不入库）
python scripts/download_model.py
python scripts/check_gesture_map.py     # 应输出 6/6 匹配

# 3. 后端 + 静态服务一起起（推荐：跨机器最容易漏的就是静态服务）
.venv\Scripts\python.exe scripts/start_dev.py

# 或者只起后端，自己另开一个静态服务
.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --port 8000
```

打开 http://127.0.0.1:8000/docs 可直接试接口；`GWC_PRELOAD=1` 可让服务启动即加载模型（首次推理不用等）。

**数据库不需要额外安装**：首次启动自动建 `data/app.db`（SQLite 单文件），并在库为空时创建一个管理员账号 **`admin / admin123456`**（可用 `GWC_ADMIN_USER` / `GWC_ADMIN_PASSWORD` 覆盖，演示前建议改掉）。删掉 `data/app.db` 即可回到全新状态。

### 接口自测

```bash
curl http://127.0.0.1:8000/api/system/status      # 数据库、四表条数、密钥来源
curl http://127.0.0.1:8000/api/health             # 模型状态与六手势映射

curl -X POST http://127.0.0.1:8000/api/predict \
  -F "frame=@data/testshots/single/r4c6.jpg;type=image/jpeg"
```

账号与记录（M2）：

```bash
# 登录拿 token（默认管理员）
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123456"}' | python -c "import json,sys;print(json.load(sys.stdin)['access_token'])")

# 上报一次手势（也可以不带 token，uid 记 null）
curl -X POST http://127.0.0.1:8000/api/records/gesture \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"gesture_type":"victory","confidence":0.88,"source":"camera"}'

# 查列表与统计
curl -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/api/records/gesture?limit=10"
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/records/gesture/stats
```

返回示例：

```json
{"ok": true, "infer_ms": 52.8, "image_size": [426, 256],
 "gestures": [{"class": "rock", "id": "love_you", "label": "爱与和平", "emoji": "🤟",
               "action": "screenshot_ai_search", "conf": 0.7976,
               "box": [100.7, 27.5, 126.4, 67.2]}]}
```

### 只想测几张照片

不用起服务，直接跑本地图片批量检测（手机拍的照片丢进一个目录即可）：

```bash
python scripts/predict_image.py 你的图片目录/ --annotate out/
```

CPU 实测单帧 28~58ms（YOLOv10n / imgsz 640），模型首次加载约 3s。

> 想知道某个手势在"手机拍的糊图 / 暗光 / 小图"下还认不认得出，用 `python scripts/stress_test.py 图片路径 --expect peace`，它会跑 17 种降质条件并告诉你能用的最小帧宽。

---

## 前端演示页

一条命令同时起后端与静态服务（跨机器开发最容易漏的就是静态服务，`file://` 下 ES Module 会加载失败）：

```bash
.venv/Scripts/python scripts/start_dev.py      # Windows
.venv/bin/python scripts/start_dev.py          # macOS / Linux
```

打开 http://127.0.0.1:8080/frontend/pages/index.html 即可。

五个页面各有用途：

| 页面 | 用途 |
| --- | --- |
| `index.html` | 演示主页：手势识别、截屏预览、图片识别、AI 问答、动作验证区 |
| `profile.html` | 个人中心：注册登录、改资料、手势统计与记录分页 |
| `admin.html` | 后台管理：全站统计、用户管理（改角色 / 删除）、三类记录明细（管理员可见） |
| `embed-demo.html` | 嵌入示例：一张普通长文页，只接 9 行代码就能用手势 |
| `selfcheck.html` | 截屏自检页：给无头浏览器读的实测结果，人工打开也能看 |

主页支持三种帧来源，**没有摄像头也能跑通整条链路**：

| 来源 | 用途 |
| --- | --- |
| 摄像头 | 正常演示，需要 `localhost` 或 https（浏览器安全限制） |
| 本地视频 | 用录制好的画面反复回放，适合排查"为什么这个手势不触发" |
| 图片序列 | 每张停留 1.5 秒，用来稳定验证"识别 → 防抖 → 动作执行" |

### SDK 接入

接入方式与可复制代码见上文[「快速接入（9 行）」](#快速接入9-行)，完整可运行版本是 `frontend/pages/embed-demo.html`。

业务方不想用默认动作实现时，传 `actions: { scroll_down: fn, screenshot: fn }` 整条接管，或用 `ctrl.actions.register(action, fn)` 单独替换。

每次触发默认会向后端上报一条记录。要带登录身份，传 `token`；嵌入第三方页面不想落库，传 `report: false`：

```js
const ctrl = new GestureWebController({
  canvas,
  token: () => localStorage.getItem('gwc_token'),  // 也支持直接传字符串
  report: true,                                     // 默认 true
});
```

上报是 fire-and-forget：数据库挂了只会让 `stats.reportErrors` 增加，**不会影响翻页，也不会弹错**。

### 个人中心

演示页右上角可进入 `frontend/pages/profile.html`：注册 / 登录、改昵称改密码、手势统计（总数 / 覆盖手势 / 平均置信度 / 近 7 天）、手势分布条、记录列表分页与删除。

### 后台管理

用管理员账号（默认 `admin / admin123456`，**演示前务必改掉**）打开 `frontend/pages/admin.html`：

- 六项统计：注册用户 / 手势记录 / 图片识别 / 问答记录 / 覆盖手势 / 平均置信度
- 手势分布条形图 + 近 7 天触发趋势
- 用户管理：按账号或昵称搜索、看每人三类记录条数、改角色、删除（连带删记录，二次确认）
- 记录明细：手势 / 图片 / 问答三个 tab，图片可直接点开原图

非管理员访问后台接口一律 403；不能改自己的角色、不能删自己、不能删掉最后一个管理员——这三条都在服务端强制（见 `docs/决策记录.md` ADR-018）。

### 测试

```bash
# 不需要浏览器
node scripts/test_sdk.mjs             # 防抖纯逻辑：9 个用例
node scripts/test_controller.mjs      # 主循环 + 动作 + 上报：15 个用例（DOM 桩，无需摄像头）
python scripts/test_api_m2.py         # 账号与记录接口：34 个用例（需后端已启动）
python scripts/test_api_m3.py         # 图片识别 + 问答 SSE + 落盘回看：40 个用例
python scripts/test_api_m4.py         # 后台管理：42 个用例（鉴权边界 / 统计口径 / 用户管理 / 级联删除）

# 需要真浏览器（截屏和页面渲染只能真渲染一次才验得出来）
node scripts/check_screenshot.mjs     # 截屏链路：5 个断言
node scripts/check_admin.mjs          # 后台页面：17 个断言（--screenshot 可存整页图）
node scripts/check_embed.mjs          # 嵌入示例页：10 个断言（走示例图，无摄像头也能跑）
```

当前基线：**9/9 + 15/15 + 34/34 + 40/40 + 42/42 + 5/5 + 17/17 + 10/10 全绿**。

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

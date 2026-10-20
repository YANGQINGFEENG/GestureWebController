# AGENTS.md —— 本项目的人机协作契约

> 无论你是 Claude、GPT、Gemini、Copilot 还是别的什么，**动手前先读完这个文件**。它保证多台电脑、多个 AI 接手时不会互相踩坑。
> 人的入口是 `README.md`，AI 的入口是本文件。

---

## 一、开局必读（按顺序，别跳）

| 顺序 | 文件 | 你要拿到什么 | 花多久 |
| --- | --- | --- | --- |
| 1 | `docs/开发进度.md` 的 front matter | 当前里程碑、正在做什么、下一步、有无阻塞 | 10 秒 |
| 2 | `docs/决策记录.md` | 哪些方案已经定了，不要再讨论/推翻 | 1 分钟 |
| 3 | `docs/开发日志.md` 最近 3 条 | 上一台机器/上一个 AI 干到哪、踩了什么坑 | 30 秒 |
| 4 | `docs/技术选型与开发计划.md` | M0~M4 的验收标准、接口契约 | 需要时查 |

**看完这四样再动手，比直接猜代码快得多。**

---

## 二、项目一句话

基于 YOLOv8/YOLOv10 手势识别的**可嵌入网页的手势控制 SDK**：前端采集摄像头帧 → 后端 YOLO 推理 → 手势映射为指令 → 前端 JS 操控页面（上翻/下翻/截屏/确定/图片识别/截屏AI搜索）。

## 三、目录地图

```
backend/app/
  api/          路由层：predict / image / chat / auth / record / admin
  services/     业务层：detector(YOLO推理) / image_rec / ai_chat / recorder
  db/           数据层：ORM 模型、会话、建表脚本
  core/         配置、鉴权、依赖注入
frontend/pages/ 页面：index(演示主页) / profile / admin / embed-demo ...
sdk/src/        可复用 SDK（capture / overlay / debounce / actions / index）
sdk/dist/       构建产物
config/         gesture_map.json（手势映射）、model.yaml（模型参数）
models/         权重目录（*.pt 不入库）
scripts/        download_model / check_gesture_map / log_progress / hooks
data/           uploads、screenshots、db（均不入库）
docs/           需求、计划、进度、决策、日志、交接
```

---

## 四、硬性约定（违反会被 review 打回）

1. **不改已生效的 ADR**。要改技术方案，先在 `docs/决策记录.md` 新增一条并注明"取代 ADR-xxx"，再动代码。
2. **类别名只出现在 `config/gesture_map.json`**。任何代码里不许硬编码 `"peace"` / `"rock"` 这类模型类别名，一律通过配置的 `id` + `model_class` 走。
3. **防抖在前端 SDK**，`/api/predict` 保持无状态，只回答"这一帧有什么手势"。
4. **数据库是可插拔日志层**。落库失败只记日志，绝不阻断手势主链路。
5. **YOLO 只出现在 `backend/app/services/detector.py`**。其他层不 import torch / ultralytics，方便替换模型与单测。
6. **密码必须哈希**（bcrypt），任何地方不得明文。
7. **权重、数据库、上传文件、密钥一律不入库**。`.pt` / `*.db` / `.env` / `data/uploads/*` 已在 `.gitignore`，不要 `git add -f`。

---

## 五、开发规范

- 分支：`dev` 上开发，`main` 保持可演示。合并用 `git merge --no-ff dev`。
- 提交：`<type>: <中文说明>`，type ∈ `feat / fix / docs / chore / refactor / test`。一次提交只做一件事。
- 接口契约改动必须同步 `docs/技术选型与开发计划.md` 第六节，并写 ADR。
- Python 用类型注解 + docstring；前端用原生 ES Module，不引框架（保证 SDK 易嵌入）。
- 中文注释可以，变量名/函数名用英文。

---

## 六、每次会话结束前（强制，这是"时刻保证"的关键）

```bash
# 1. 更新进度看板（front matter 四个字段 + 清单勾选）
#    docs/开发进度.md

# 2. 追加日志（自动带时间/主机名/分支/commit，并自动刷新看板时间戳）
python scripts/log_progress.py "本次做了什么" --next "下一步计划"

# 3. 有决策就补 ADR：docs/决策记录.md

# 4. 提交
git add -A && git commit -m "feat: xxx"
```

仓库已装提交前钩子：**改了 `backend/ frontend/ sdk/ scripts/ config/` 却没更新 `docs/开发进度.md`，提交会被拒绝**。安装钩子见 `scripts/install_hooks.sh`。

### 改完代码请跑这三条（都不需要摄像头 / 浏览器）

```bash
node scripts/test_sdk.mjs           # 防抖纯逻辑（9 用例）
node scripts/test_controller.mjs    # SDK 主循环集成（8 用例，DOM 桩）
python scripts/check_gesture_map.py # 配置里的类别名与权重是否匹配
```

前端没有构建步骤、没有 node_modules 依赖，测试用 Node 内置模块直接跑——**不要为了测试引入打包工具**。

---

## 七、当前状态

以 `docs/开发进度.md` 为准，本文件不重复记录进度（避免两处不一致）。

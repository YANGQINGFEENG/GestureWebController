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
  api/          路由层：predict / recognize / chat / auth / records / admin / system / deps(依赖注入) / common(上传校验)
  services/    业务层：detector(YOLO推理) / storage(图片落盘) / describe(结果文案) / llm(问答双 provider)
  db/           数据层：models(四张表) / session / repository(全部查询) / seed
  core/         配置加载、密码哈希与 JWT
frontend/pages/ 页面：index(演示主页) / profile(个人中心) / selfcheck(截屏自检)（M4 加 admin / embed-demo）
frontend/assets/ auth.js（登录态与 api 封装）
sdk/src/        可复用 SDK（capture / overlay / debounce / actions / screenshot / index）
sdk/vendor/     html2canvas.min.js（随 SDK 分发，离线可用，勿手改）
sdk/dist/       构建产物
config/         gesture_map.json（手势映射）、model.yaml（模型参数）、app.yaml（数据库/鉴权/记录/上传）
models/         权重目录（*.pt 不入库）
scripts/        download_model / check_gesture_map / predict_image / stress_test / start_dev /
                log_progress / test_sdk / test_controller / test_api_m2 / test_api_m3 /
                check_screenshot / hooks
data/           uploads、screenshots、app.db、.jwt_secret（均不入库；/media/uploads 只暴露 uploads）
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
7. **权重、数据库、上传文件、密钥一律不入库**。`.pt` / `*.db` / `.env` / `data/uploads/*` / `data/.jwt_secret` 已在 `.gitignore`，不要 `git add -f`。
8. **依赖注入只传 `AuthUser` 快照，不传 ORM 对象**（ADR-013）。需要完整用户信息时用接口自己的 Session 重新查，否则会出现 `Object is already attached to session`。
9. **所有 SQL 集中在 `db/repository.py`**，API 层不写查询语句。

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

### 改完代码请跑这四条（都不需要摄像头 / 浏览器）

```bash
node scripts/test_sdk.mjs            # 防抖纯逻辑（9 用例）
node scripts/test_controller.mjs     # SDK 主循环 + 动作 + 上报（15 用例，DOM 桩）
python scripts/test_api_m2.py        # 账号与记录接口（34 用例，需后端已启动）
python scripts/test_api_m3.py        # 图片识别 + 问答 SSE + 落盘回看（40 用例，需后端已启动）
python scripts/check_gesture_map.py  # 配置里的类别名与权重是否匹配

# 需要浏览器（截屏只在浏览器里成立）：先起静态服务，再跑自检
.venv/Scripts/python -m http.server 8080 --bind 127.0.0.1 --directory .
node scripts/check_screenshot.mjs    # 无头 Chrome 实测截屏（5 断言：尺寸/非空白/亮度/耗时/成功）
```

改了截屏相关代码（`sdk/src/screenshot.js`、`actions.js` 的 screenshot 分支、`selfcheck.html`）**必须**跑最后一条——
截屏是不是空白，代码审查看不出来，只有真渲染一次才知道。

前端没有构建步骤、没有 node_modules 依赖，测试用 Node 内置模块直接跑——**不要为了测试引入打包工具**。

---

## 七、当前状态

以 `docs/开发进度.md` 为准，本文件不重复记录进度（避免两处不一致）。

# CLAUDE.md

本仓库的 AI 协作说明统一维护在 **[AGENTS.md](AGENTS.md)**，请先读它（含开局必读文件清单、硬性约定、每次会话结束的强制动作）。

按顺序读：

1. `docs/开发进度.md` —— front matter 是当前状态（里程碑 / 正在做什么 / 下一步），正文是清单
2. `docs/决策记录.md` —— 已生效的技术决策，不要推翻；要改就新增 ADR
3. `docs/开发日志.md` —— 最近三条，看上一台机器干到哪、踩了什么坑
4. `AGENTS.md` —— 目录地图、硬性约定、提交规范

三条最容易踩的规矩：类别名只写在 `config/gesture_map.json`；YOLO 只出现在 `backend/app/services/detector.py`；改代码必须同时更新进度看板（提交前钩子会拦）。

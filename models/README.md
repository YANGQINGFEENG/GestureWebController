# models —— 模型权重目录

权重体积较大，**不纳入版本管理**（见根目录 `.gitignore` 的 `models/*.pt`）。
换电脑后本目录是空的，需要自己把权重放进来——这一步漏了，后端启动会直接 `FileNotFoundError`。

## 当前使用的权重

| 文件 | 用途 | 大小 | 精度 |
| ---- | ---- | ---- | ---- |
| `YOLOv10n_gestures.pt` | 手势检测（34 类，HaGRIDv2） | 21.4 MB（22,442,394 字节） | mAP 88.2 |

**完整性指纹**（换机器、从 U 盘/网盘拷贝后请核对）：

```
sha256 = bf628ce3a1638ab19a7ab635c0f674cfec2988989f42f1eef394a6dce5a35b9f
```

## 获取方式（任选其一）

**A. 一条命令下载（推荐，新机器首选）**

```bash
python scripts/download_model.py           # 下载 + 自动校验大小与 sha256
python scripts/download_model.py --verify  # 只校验已有文件
python scripts/download_model.py --force   # 文件损坏时重新下
```

**B. 从旧电脑拷过来**

权重只有 21.4 MB，U 盘 / 网盘 / 局域网直接拷 `models/YOLOv10n_gestures.pt` 到新机器的同名路径，
然后跑 `python scripts/download_model.py --verify` 确认没拷坏。

**C. 下载卡住时**

上游在俄罗斯的 Sbercloud 对象存储（`rndml-team-cv.obs.ru-moscow-1.hc.sbercloud.ru`），
国内访问**多数时候正常**（实测 HEAD 响应 3.5s），但偶发很慢。可以：

- 多试几次（脚本支持重跑，已下完的会跳过）；
- 或者用 B 方案从旧电脑拷——这是最可靠的，21MB 而已；
- 脚本已内置「证书校验失败自动降级」，不用手动处理代理证书问题。

## 协议与来源

- 权重来自 [HaGRIDv2](https://github.com/hukenovs/hagrid) 官方发布的 YOLOv10 训练结果，协议 **CC BY-SA 4.0**。
- 本项目只做推理调用，未修改权重。
- 类别名以权重内置的 `names` 为准，与 `config/gesture_map.json` 的对应关系用
  `python scripts/check_gesture_map.py` 校验（当前 6/6 匹配）。

## 想换更大模型

```bash
python scripts/download_model.py --variant x    # YOLOv10x，精度 89.4，CPU 上会明显变慢
```

换完要把 `config/model.yaml` 的 `path` 指过去，并重跑 `check_gesture_map.py`（x 版权重类别一致，通常能直接过）。

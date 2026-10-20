"""把检测结果翻译成「人话」。

需求文档 5.3 里 `image_record` 有两个文本字段，定位不同：

| 字段 | 含义 | 例 |
| --- | --- | --- |
| `label` | 分类标签，短、可统计、可做筛选 | `张开手掌` |
| `result` | 给用户看的整段描述 | `识别到 🖐️ 张开手掌，置信度 94.0%，对应动作「截屏」。` |

为什么单独一层而不是写在接口里：M3-5 的 AI 问答会把这段文本当上下文，
M4 后台也要按 label 聚合统计，两处都依赖同一套措辞规则，集中一处才不会漂移。
"""

from __future__ import annotations

NO_GESTURE_LABEL = "未识别"


def describe(gestures: list[dict], *, raw_count: int = 0, image_size: list[int] | None = None) -> tuple[str, str]:
    """返回 (result 文本, label)。

    `gestures` 是 detector 输出的手势列表（已按置信度降序）；
    `raw_count` 是模型原始检测框数量，用来区分「画面里没手」和「有手但不是六种预设手势」。
    """
    if not gestures:
        if raw_count > 0:
            return (
                f"图中检测到 {raw_count} 个手部目标，但都不属于预设的六种手势，"
                "建议正对镜头、手掌完整入画后重试。",
                NO_GESTURE_LABEL,
            )
        return ("图中未检测到手部目标，请把手抬到画面中央再试。", NO_GESTURE_LABEL)

    if len(gestures) == 1:
        item = gestures[0]
        text = (
            f"识别到 {_name(item)}，置信度 {item['conf'] * 100:.1f}%"
            f"，对应动作「{item.get('action_label') or item['action']}」。"
        )
        if image_size:
            text += f"（图片 {image_size[0]}×{image_size[1]}）"
        return text, item["label"]

    parts = [
        f"{_name(item)}（{item['conf'] * 100:.1f}%）" for item in gestures
    ]
    top = gestures[0]
    return (
        f"共识别到 {len(gestures)} 个手势：{'、'.join(parts)}；"
        f"主标签为「{top['label']}」，对应动作「{top.get('action_label') or top['action']}」。",
        top["label"],
    )


def _name(item: dict) -> str:
    """emoji + 中文名的统一写法，没配 emoji 时不留多余空格。"""
    emoji = item.get("emoji") or ""
    return f"{emoji} {item['label']}".strip()

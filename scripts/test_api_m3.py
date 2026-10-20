"""M3 图片识别接口端到端测试：上传 → 识别 → 落盘 → 入库 → 回看 → 边界。

只用标准库（urllib + 手写 multipart），任何装了 Python 的机器都能跑，不引 requests。
需要后端已启动：

    python scripts/test_api_m3.py                          # 默认 http://127.0.0.1:8000
    python scripts/test_api_m3.py --base-url http://127.0.0.1:8011
    python scripts/test_api_m3.py --image data/testshots/single/r1c1.jpg

退出码 0 表示全部通过。
"""

from __future__ import annotations

import argparse
import json
import random
import string
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PASS, FAIL = "✅", "❌"
results: list[tuple[bool, str, str]] = []

# 本机常设 HTTP_PROXY，会连 127.0.0.1 也走代理导致 502，显式绕过
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def check(name: str, condition: bool, detail: str = "") -> bool:
    results.append((condition, name, detail))
    print(f"{PASS if condition else FAIL} {name}" + (f"  ({detail})" if detail else ""))
    return condition


def _multipart(
    fields: dict[str, str],
    files: dict[str, tuple[str, bytes, str]],
) -> tuple[bytes, str]:
    boundary = f"----gwc{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
        )
    for key, (filename, content, content_type) in files.items():
        chunks.append(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"; '
                f'filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n'
            ).encode()
        )
        chunks.append(content)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def post_image(
    base: str,
    path: str,
    *,
    content: bytes,
    filename: str = "shot.jpg",
    content_type: str = "image/jpeg",
    fields: dict[str, str] | None = None,
    token: str | None = None,
    timeout: int = 30,
) -> tuple[int, dict]:
    body, ctype = _multipart(fields or {}, {"image": (filename, content, content_type)})
    req = urllib.request.Request(f"{base}{path}", data=body, method="POST")
    req.add_header("Content-Type", ctype)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    return _send(req, timeout)


def _send(req: urllib.request.Request, timeout: int = 30) -> tuple[int, dict]:
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, {"_raw_len": len(raw)}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw[:200].decode("utf-8", "replace")}
    except urllib.error.URLError as exc:
        print(f"\n无法连接 {req.full_url}：{exc.reason}\n请先启动后端：.venv/Scripts/python scripts/start_dev.py")
        raise SystemExit(2) from exc


def get(base: str, path: str, token: str | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(f"{base}{path}", method="GET")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    return _send(req)


def get_bytes(base: str, path: str) -> tuple[int, bytes]:
    req = urllib.request.Request(f"{base}{path}", method="GET")
    try:
        with _OPENER.open(req, timeout=20) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""


def post_sse(
    base: str, path: str, body: dict, token: str | None = None, timeout: int = 60
) -> tuple[int, list[dict]]:
    """读完整条 SSE 流并解析出事件列表（问答是流式的，不能只读第一段）。"""
    req = urllib.request.Request(
        f"{base}{path}", data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST"
    )
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    events: list[dict] = []
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            status = resp.status
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    events.append(json.loads(line[5:].strip()))
                except json.JSONDecodeError:
                    continue
            return status, events
    except urllib.error.HTTPError as exc:
        return exc.code, events


def rand_name(prefix: str = "m3_") -> str:
    return prefix + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--image",
        default=str(ROOT / "data" / "testshots" / "single" / "r1c1.jpg"),
        help="一张能识别出手势的图片（默认用拼图裁出来的单图）",
    )
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    image_path = Path(args.image)

    print(f"目标服务：{base}\n测试图片：{image_path}\n" + "-" * 72)
    token = ""
    if not image_path.exists():
        print(f"{FAIL} 测试图片不存在：{image_path}")
        print("  可先跑 python scripts/predict_image.py --help 了解可用素材，或用 --image 指定")
        return 1
    shot = image_path.read_bytes()

    # ---- 0. 前置：服务与数据库 ----
    code, status = get(base, "/api/system/status")
    db_ok = bool(status.get("database", {}).get("available"))
    check("系统状态可读", code == 200, f"HTTP {code}")
    check("数据库可用（否则记录类断言跳过）", db_ok, f"db={db_ok}")

    code, health = get(base, "/api/health")
    check("健康检查含六种手势", code == 200 and len(health.get("gestures", [])) == 6,
          f"HTTP {code} / {len(health.get('gestures', []))} 个")

    # ---- 1. 主链路：上传识别 ----
    # 预热：首个请求要加载权重（本机约 3s）。不预热会让下面"总耗时 < 3s"的断言误报，
    # 而这条断言的意图是"稳定状态下够快"，不是"冷启动也够快"。
    post_image(base, "/api/image/recognize", content=shot, fields={"source": "upload"})

    code, res = post_image(base, "/api/image/recognize", content=shot, fields={"source": "upload"},
                           token=None)
    check("上传识别返回 200", code == 200 and res.get("ok") is True, f"HTTP {code}")
    check("result 是给用户看的描述", isinstance(res.get("result"), str) and len(res["result"]) > 8,
          res.get("result", "")[:48])
    check("label 有值（未识别也算）", bool(res.get("label")), f"label={res.get('label')}")
    check("原图已落盘并给出 img_url", bool(res.get("img_url")), str(res.get("img_url")))
    check("返回耗时明细", isinstance(res.get("timings"), dict) and "infer_ms" in res["timings"],
          str(res.get("timings")))
    check("单次识别总耗时 < 3000ms（需求 6.1）",
          float(res.get("timings", {}).get("total_ms", 9e9)) < 3000,
          f"{res.get('timings', {}).get('total_ms')}ms")

    img_url = res.get("img_url") or ""
    if img_url:
        code_img, blob = get_bytes(base, img_url)
        check("img_url 可直接访问（/media/uploads 挂载生效）",
              code_img == 200 and len(blob) > 1000, f"HTTP {code_img} / {len(blob)}B")

    # ---- 2. 落库 ----
    record = res.get("record") or {}
    if db_ok:
        check("识别记录已入库", res.get("saved") is True and record.get("record_id"),
              f"saved={res.get('saved')} id={record.get('record_id')}")
        check("入库 img_path 与返回一致", record.get("img_path") == res.get("img_path"),
              f"{record.get('img_path')}")
        check("入库 label / result 与返回一致",
              record.get("label") == res.get("label") and record.get("result") == res.get("result"),
              f"label={record.get('label')}")
        check("source 落库正确", record.get("source") == "upload", f"source={record.get('source')}")
        check("未登录 uid 记 null（与手势上报同策略）", record.get("uid") is None,
              f"uid={record.get('uid')}")
    else:
        check("数据库不可用时仍返回识别结果且 saved=false",
              code == 200 and res.get("saved") is False, f"saved={res.get('saved')}")

    # ---- 3. 登录用户：uid 关联 + 记录列表可查 ----
    if db_ok:
        username, password = rand_name(), "Test@123456"
        code, reg = _send(_json_request(f"{base}/api/auth/register",
                                        {"username": username, "password": password}, "POST"))
        token = reg.get("access_token", "")
        uid = (reg.get("user") or {}).get("uid")
        check("注册测试账号成功", code == 201 and bool(token), f"HTTP {code}")

        code, res2 = post_image(base, "/api/image/recognize", content=shot,
                                fields={"source": "screenshot"}, token=token)
        check("登录用户识别成功", code == 200 and res2.get("saved") is True, f"HTTP {code}")
        check("uid 正确关联到记录", (res2.get("record") or {}).get("uid") == uid,
              f"uid={uid} 记录={(res2.get('record') or {}).get('uid')}")
        check("screenshot 来源落库", (res2.get("record") or {}).get("source") == "screenshot",
              f"source={(res2.get('record') or {}).get('source')}")

        code, listing = get(base, "/api/records/image?limit=50", token=token)
        ids = [item.get("record_id") for item in listing.get("items", [])]
        check("个人中心能查到本次识别记录",
              code == 200 and (res2.get("record") or {}).get("record_id") in ids,
              f"共 {len(ids)} 条")

        code, _ = get(base, "/api/records/image")
        check("未登录查记录列表返回 401", code == 401, f"HTTP {code}")

    # ---- 4. 边界与错误码 ----
    code, _ = post_image(base, "/api/image/recognize", content=shot, content_type="text/plain",
                         filename="a.txt")
    check("非图片类型返回 415", code == 415, f"HTTP {code}")

    code, _ = post_image(base, "/api/image/recognize", content=b"")
    check("空文件返回 400", code == 400, f"HTTP {code}")

    code, _ = post_image(base, "/api/image/recognize", content=b"not an image at all" * 50)
    check("内容不是图片返回 400", code == 400, f"HTTP {code}")

    code, _ = post_image(base, "/api/image/recognize", content=b"\x00" * (9 * 1024 * 1024))
    check("超过 8MB 返回 413", code == 413, f"HTTP {code}")

    code, _ = post_image(base, "/api/image/recognize", content=shot, fields={"conf": "1.5"})
    check("conf 越界返回 422", code == 422, f"HTTP {code}")

    code, _ = post_image(base, "/api/image/recognize", content=shot, fields={"imgsz": "99"})
    check("imgsz 越界返回 422", code == 422, f"HTTP {code}")

    code, _ = post_image(base, "/api/image/recognize", content=shot, fields={"source": "hack"})
    check("非法 source 返回 422", code == 422, f"HTTP {code}")

    body, ctype = _multipart({}, {})
    req = urllib.request.Request(f"{base}/api/image/recognize", data=body, method="POST")
    req.add_header("Content-Type", ctype)
    code, _ = _send(req)
    check("未带文件返回 422", code == 422, f"HTTP {code}")

    # ---- 5. 静态目录不越界 ----
    code, _ = get_bytes(base, "/media/app.db")
    check("data 根目录未暴露（/media/app.db 不可下载）", code == 404, f"HTTP {code}")

    # ---- 6. 无手势图片：给出可读解释而不是空白 ----
    code, res3 = post_image(base, "/api/image/recognize", content=shot, fields={"conf": "0.99"})
    check("阈值拉高后仍返回可读解释", code == 200 and len(res3.get("result", "")) > 8,
          str(res3.get("result"))[:48])

    # ---- 7. AI 问答（SSE 流式） ----
    code, info = get(base, "/api/chat/info")
    provider = (info.get("llm") or {}).get("provider")
    check("问答模型信息可读", code == 200 and bool(provider), f"provider={provider}")

    code, events = post_sse(base, "/api/chat", {"question": "支持哪些手势？"})
    kinds = [e.get("type") for e in events]
    answer = "".join(e.get("text", "") for e in events if e.get("type") == "delta")
    done = next((e for e in events if e.get("type") == "done"), {})
    check("问答返回 SSE 流（start → delta → done）",
          code == 200 and kinds[:1] == ["start"] and "delta" in kinds and kinds[-1:] == ["done"],
          f"HTTP {code} / {len(events)} 个事件")
    check("流式拼出的回答非空", len(answer) > 10, f"{len(answer)} 字")
    check("回答内容覆盖手势清单", all(k in answer for k in ("下翻页", "上翻页", "截屏")), answer[:24])
    if db_ok:
        check("问答已入库并返回 chat_id",
              done.get("saved") is True and bool(done.get("chat_id")), f"chat_id={done.get('chat_id')}")

    code, events2 = post_sse(base, "/api/chat",
                             {"question": "这个结论什么意思？",
                              "context": "识别到 🖐️ 张开手掌，置信度 73.9%"})
    answer2 = "".join(e.get("text", "") for e in events2 if e.get("type") == "delta")
    check("带识别上下文时回答引用该结论", code == 200 and "识别" in answer2, answer2[:30])

    code, _ = post_sse(base, "/api/chat", {"question": ""})
    check("空问题返回 422", code == 422, f"HTTP {code}")

    code, _ = post_sse(base, "/api/chat", {"question": "x" * 2001})
    check("超长问题返回 422", code == 422, f"HTTP {code}")

    if db_ok and token:
        # 先用同一个账号问一句，才能验证"自己的问答记录"能查到（游客记录 uid 为 null，查不到是正确行为）
        post_sse(base, "/api/chat", {"question": "我这条问答会记录吗？"}, token=token)
        code, listing = get(base, "/api/records/chat?limit=10", token=token)
        ids = [item.get("chat_id") for item in listing.get("items", [])]
        check("个人中心能查到问答记录", code == 200 and len(ids) >= 1, f"共 {len(ids)} 条")

    # ---- 汇总 ----
    print("-" * 72)
    passed = sum(1 for ok, _, _ in results if ok)
    for ok, name, detail in results:
        if not ok:
            print(f"  {FAIL} {name}  ({detail})")
    print(f"{PASS if passed == len(results) else FAIL} {passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


def _json_request(url: str, body: dict, method: str) -> urllib.request.Request:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method=method)
    req.add_header("Content-Type", "application/json")
    return req


if __name__ == "__main__":
    sys.exit(main())

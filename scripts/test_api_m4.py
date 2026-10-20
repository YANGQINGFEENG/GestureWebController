"""M4-1 后台管理接口端到端测试：鉴权边界 / 统计口径 / 用户管理 / 三类记录 / 选图回看。

只用标准库，任何装了 Python 的机器都能跑。需要后端已启动：

    python scripts/test_api_m4.py                          # 默认 http://127.0.0.1:8000
    python scripts/test_api_m4.py --base-url http://127.0.0.1:8011
    python scripts/test_api_m4.py --admin-user admin --admin-pass admin123456

测试会注册一个临时用户并把它删掉，不会动已有账号；管理员密码从环境变量
GWC_ADMIN_PASSWORD 读，缺省用种子里写的 admin123456。
"""

from __future__ import annotations

import argparse
import json
import os
import random
import string
import sys
import urllib.error
import urllib.parse
import urllib.request
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


def call(
    base: str,
    path: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    token: str | None = None,
) -> tuple[int, dict]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"{base}{path}", data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    return _send(req)


def head_status(base: str, path: str) -> tuple[int, str]:
    """轻量 GET，只关心状态码与 Content-Type（用于验证图片地址可访问）。"""
    req = urllib.request.Request(f"{base}{path}", method="GET")
    try:
        with _OPENER.open(req, timeout=20) as resp:
            resp.read(64)
            return resp.status, resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        return exc.code, ""


def rand_name(prefix: str = "m4_") -> str:
    return prefix + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--admin-user", default=os.getenv("GWC_ADMIN_USER", "admin"))
    parser.add_argument("--admin-pass", default=os.getenv("GWC_ADMIN_PASSWORD", "admin123456"))
    parser.add_argument(
        "--image",
        default=str(ROOT / "data" / "testshots" / "single" / "r1c1.jpg"),
        help="用于制造一条图片记录的手势图",
    )
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    image_path = Path(args.image)

    print(f"目标服务：{base}\n管理员：{args.admin_user}\n" + "-" * 72)

    # ---- 0. 管理员登录 ----
    code, res = call(base, "/api/auth/login", method="POST",
                     body={"username": args.admin_user, "password": args.admin_pass})
    token = (res or {}).get("access_token", "")
    if not check("管理员登录成功", code == 200 and bool(token), f"HTTP {code}"):
        print("\n管理员密码不对？用 --admin-pass 指定，或检查 config/app.yaml 的 auth.admin 配置。")
        return 1
    admin_uid = (res.get("user") or {}).get("uid")

    # ---- 1. 鉴权边界 ----
    code, _ = call(base, "/api/admin/overview")
    check("未登录访问后台返回 401", code == 401, f"HTTP {code}")

    username = rand_name()
    password = "test123456"
    code, res = call(base, "/api/auth/register", method="POST",
                     body={"username": username, "password": password})
    user_token = (res or {}).get("access_token", "")
    user_uid = ((res or {}).get("user") or {}).get("uid")
    check("注册普通测试用户", code in (200, 201) and bool(user_token), f"{username} / HTTP {code}")

    code, _ = call(base, "/api/admin/overview", token=user_token)
    check("普通用户访问后台返回 403（不是 404，便于排障）", code == 403, f"HTTP {code}")
    code, _ = call(base, "/api/admin/users", token=user_token)
    check("普通用户读用户列表同样 403", code == 403, f"HTTP {code}")

    # ---- 2. 总览口径 ----
    code, ov = call(base, "/api/admin/overview", token=token)
    counts = ov.get("counts") or {}
    check("总览可读", code == 200 and ov.get("ok") is True, f"HTTP {code}")
    check("总览含四张表计数",
          all(k in counts for k in ("users", "gesture_records", "image_records", "chat_records")),
          json.dumps(counts, ensure_ascii=False))
    check("总览含覆盖手势数与平均置信度",
          "gesture_kinds" in (ov.get("summary") or {}) and "avg_confidence" in (ov.get("summary") or {}))

    # 用户数与用户接口的 total 必须对得上，否则就是分页/计数写了两套逻辑
    code2, users0 = call(base, "/api/admin/users?limit=1", token=token)
    check("总览用户数与用户列表 total 一致",
          counts.get("users") == users0.get("total"),
          f"{counts.get('users')} vs {users0.get('total')}")
    check("总览手势总数与统计明细一致",
          counts.get("gesture_records") == (ov.get("gesture_stats") or {}).get("total"))

    # ---- 3. 用户列表 ----
    code, ulist = call(base, "/api/admin/users?limit=5", token=token)
    items = ulist.get("items") or []
    check("用户列表可读", code == 200 and len(items) > 0, f"{len(items)} 条")
    first = items[0] if items else {}
    check("用户列表不含密码字段",
          all("password" not in k and "password_hash" not in k for k in first),
          ", ".join(first.keys()))
    check("用户列表带三类记录条数",
          isinstance(first.get("counts"), dict) and set(first["counts"]) == {"gesture", "image", "chat"},
          json.dumps(first.get("counts"), ensure_ascii=False))

    code, found = call(base, f"/api/admin/users?q={urllib.parse.quote(username)}", token=token)
    hit = found.get("items") or []
    check("按账号搜索能命中刚注册的用户",
          code == 200 and len(hit) == 1 and hit[0]["username"] == username,
          f"{len(hit)} 条")

    # 中文关键词也要能搜（账号是 ASCII，但昵称可能是中文）
    code, none = call(base, f"/api/admin/users?q={urllib.parse.quote('zzz_不存在_zzz')}", token=token)
    check("搜不到时返回空列表而不是报错（含中文关键词）",
          code == 200 and (none.get("items") or []) == [])
    check("搜索结果的 total 也随条件收敛", (none.get("total") or 0) == 0)

    code, paged = call(base, "/api/admin/users?limit=2&offset=1", token=token)
    check("用户列表分页生效", code == 200 and len(paged.get("items") or []) <= 2,
          f"offset=1 拿到 {len(paged.get('items') or [])} 条")

    # ---- 4. 用户管理 ----
    code, _ = call(base, "/api/admin/users?limit=0", token=token)
    check("limit 越界返回 422", code == 422, f"HTTP {code}")

    code, res = call(base, f"/api/admin/users/{user_uid}", method="PATCH",
                     body={"role": "admin"}, token=token)
    check("管理员可提升他人为管理员",
          code == 200 and (res.get("user") or {}).get("role") == "admin", f"HTTP {code}")
    code, me = call(base, "/api/auth/me", token=user_token)
    check("被提升的账号立即拿到管理员角色",
          (me.get("user") or {}).get("role") == "admin")

    code, res = call(base, f"/api/admin/users/{user_uid}", method="PATCH",
                     body={"role": "user"}, token=token)
    check("可再降回普通用户", code == 200 and (res.get("user") or {}).get("role") == "user")

    code, _ = call(base, f"/api/admin/users/{admin_uid}", method="PATCH",
                   body={"role": "user"}, token=token)
    check("不能改自己的角色（防止锁死后台）", code == 422, f"HTTP {code}")

    code, _ = call(base, "/api/admin/users/999999", method="PATCH",
                   body={"role": "admin"}, token=token)
    check("改不存在的用户返回 404", code == 404, f"HTTP {code}")

    code, _ = call(base, f"/api/admin/users/{user_uid}", method="PATCH",
                   body={"role": "superuser"}, token=token)
    check("非法角色返回 422", code == 422, f"HTTP {code}")

    code, _ = call(base, f"/api/admin/users/{admin_uid}", method="DELETE", token=token)
    check("不能删除自己", code == 422, f"HTTP {code}")

    # ---- 5. 三类记录 ----
    code, grec = call(base, "/api/admin/records?limit=5", token=token)
    check("全站手势记录可读",
          code == 200 and "total" in grec and isinstance(grec.get("items"), list),
          f"total={grec.get('total')}")
    if grec.get("items"):
        row = grec["items"][0]
        check("手势记录字段齐全",
              all(k in row for k in ("record_id", "gesture_type", "action", "confidence", "create_time")))

    # 用测试用户先制造一条图片记录，确保 images 接口有东西可验
    if image_path.exists():
        import uuid as _uuid

        boundary = f"----gwc{_uuid.uuid4().hex}"
        fields = {"source": "upload"}
        chunks = [
            f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
            for k, v in fields.items()
        ]
        chunks.append(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="image"; '
                f'filename="m4.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'
            ).encode()
        )
        chunks.append(image_path.read_bytes())
        chunks.append(b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode())
        req = urllib.request.Request(
            f"{base}/api/image/recognize", data=b"".join(chunks), method="POST"
        )
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        req.add_header("Authorization", f"Bearer {user_token}")
        recog_code, recog = _send(req, timeout=60)
        check("为测试用户制造一条图片记录", recog_code == 200 and recog.get("saved") is True,
              f"HTTP {recog_code} / record={(recog.get('record') or {}).get('record_id')}")
    else:
        check("测试图片存在", False, str(image_path))

    code, irec = call(base, "/api/admin/images?limit=5", token=token)
    iitems = irec.get("items") or []
    check("全站图片记录可读", code == 200 and isinstance(iitems, list), f"{len(iitems)} 条")
    with_url = [r for r in iitems if r.get("img_url")]
    check("图片记录带可直接访问的地址", bool(with_url), f"{len(with_url)} 条有 img_url")
    if with_url:
        status, ctype = head_status(base, with_url[0]["img_url"])
        check("图片地址能打开且是图片",
              status == 200 and ctype.startswith("image/"), f"HTTP {status} / {ctype}")

    code, crec = call(base, "/api/admin/chats?limit=3&preview=20", token=token)
    citems = crec.get("items") or []
    check("全站问答记录可读", code == 200 and isinstance(citems, list), f"{len(citems)} 条")
    if citems:
        longest = max(len(r.get("answer") or "") for r in citems)
        check("问答按 preview 截断（<=21 字符）", longest <= 21, f"最长 {longest} 字")

    code, full = call(base, "/api/admin/chats?limit=1&preview=0", token=token)
    fitems = full.get("items") or []
    check("preview=0 时不截断", code == 200 and (not fitems or "…" not in (fitems[0].get("answer") or "")[-2:]),
          f"{len(fitems)} 条")

    # ---- 6. 级联删除 ----
    code, seq = call(base, "/api/admin/records?limit=1", token=token)
    before = (seq.get("items") or [{}])[0].get("uid")

    code, _ = call(base, f"/api/admin/users/{user_uid}", method="DELETE", token=token)
    check("管理员可删除用户", code == 200, f"HTTP {code}")

    code, gone = call(base, f"/api/admin/users?q={urllib.parse.quote(username)}", token=token)
    check("删除后搜不到该用户", code == 200 and (gone.get("items") or []) == [])

    code, allrec = call(base, "/api/admin/records?limit=200", token=token)
    left = [r for r in (allrec.get("items") or []) if r.get("uid") == user_uid]
    check("用户的手势记录随用户级联删除", left == [], f"残留 {len(left)} 条")

    code, allimg = call(base, "/api/admin/images?limit=200", token=token)
    left_img = [r for r in (allimg.get("items") or []) if r.get("uid") == user_uid]
    check("用户的图片记录随用户级联删除", left_img == [], f"残留 {len(left_img)} 条")

    code, _ = call(base, f"/api/admin/users/{user_uid}", method="DELETE", token=token)
    check("删除不存在的用户返回 404", code == 404, f"HTTP {code}")

    # ---- 7. 后台页面 ----
    page = ROOT / "frontend" / "pages" / "admin.html"
    check("后台页面文件存在", page.exists(), page.name)
    if page.exists():
        html = page.read_text(encoding="utf-8")
        check("后台页面覆盖四类视图",
              all(k in html for k in ("用户管理", "手势分布", "图片识别", "问答记录")))
        check("后台页面不写死 API 地址（走 auth.js 的 endpoint）",
              "127.0.0.1" not in html)

    # ---- 汇总 ----
    print("-" * 72)
    passed = sum(1 for ok, _, _ in results if ok)
    total = len(results)
    print(f"{passed}/{total} 通过" + ("" if passed == total else "  ← 有失败项，见上方 ❌"))
    if before is not None:
        print(f"（测试前最新一条记录属于 uid={before}，供人工核对后台表格）")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())

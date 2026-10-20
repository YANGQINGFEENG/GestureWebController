"""M2 接口端到端测试：注册 → 登录 → 上报 → 列表 → 删除 → 鉴权边界。

只用标准库（urllib），不引入 requests / httpx，任何装了 Python 的机器都能跑。
需要后端已启动：

    python scripts/test_api_m2.py                      # 默认 http://127.0.0.1:8000
    python scripts/test_api_m2.py --base-url http://127.0.0.1:8001

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

PASS, FAIL = "✅", "❌"
results: list[tuple[bool, str, str]] = []

# 本机开发环境常设 HTTP_PROXY，urllib 会连本地服务也走代理导致 502，这里显式绕过
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(
    method: str,
    url: str,
    body: dict | None = None,
    token: str | None = None,
) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with _OPENER.open(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw}
        return exc.code, payload
    except urllib.error.URLError as exc:
        print(f"\n无法连接 {url}：{exc.reason}\n请先启动后端：.venv/Scripts/python scripts/start_dev.py")
        raise SystemExit(2) from exc


def check(name: str, condition: bool, detail: str = "") -> bool:
    results.append((condition, name, detail))
    print(f"{PASS if condition else FAIL} {name}" + (f"  ({detail})" if detail else ""))
    return condition


def rand_name(prefix: str = "t") -> str:
    return prefix + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    print(f"目标服务：{base}\n" + "-" * 72)

    # ---- 0. 系统状态 ----
    code, status = request("GET", f"{base}/api/system/status")
    check("系统状态可读", code == 200 and status.get("database", {}).get("available") is True,
          f"HTTP {code} / db={status.get('database', {}).get('available')}")
    if code != 200 or not status.get("database", {}).get("available"):
        print("\n数据库不可用，后续用例跳过。请检查 data/app.db 与 config/app.yaml")
        return 1

    # ---- 1. 注册 ----
    username = rand_name("m2_")
    password = "Test@123456"
    code, reg = request("POST", f"{base}/api/auth/register",
                        {"username": username, "password": password, "nickname": "测试用户"})
    check("注册成功返回 201 与 token", code == 201 and "access_token" in reg, f"HTTP {code}")
    token = reg.get("access_token", "")
    register_uid = reg.get("user", {}).get("uid")

    # ---- 2. 注册边界 ----
    code, _ = request("POST", f"{base}/api/auth/register", {"username": username, "password": password})
    check("重复账号被拒（409）", code == 409, f"HTTP {code}")

    code, _ = request("POST", f"{base}/api/auth/register", {"username": rand_name(), "password": "123"})
    check("弱密码被拒（422）", code == 422, f"HTTP {code}")

    code, _ = request("POST", f"{base}/api/auth/register", {"username": "ab", "password": password})
    check("非法账号名被拒（422）", code == 422, f"HTTP {code}")

    # ---- 3. 登录 ----
    code, login = request("POST", f"{base}/api/auth/login", {"username": username, "password": password})
    check("登录成功", code == 200 and "access_token" in login, f"HTTP {code}")
    token = login.get("access_token", token)

    code, _ = request("POST", f"{base}/api/auth/login", {"username": username, "password": "wrong-pass"})
    check("密码错误被拒（401）", code == 401, f"HTTP {code}")

    code, _ = request("POST", f"{base}/api/auth/login", {"username": "no_such_user_xyz", "password": password})
    check("不存在的账号同样返回 401（不可枚举）", code == 401, f"HTTP {code}")

    # ---- 4. 我的信息 ----
    code, me = request("GET", f"{base}/api/auth/me", token=token)
    check("带 token 取到本人信息", code == 200 and me.get("user", {}).get("username") == username,
          f"HTTP {code}")
    check("响应中不含密码字段", "password" not in json.dumps(me.get("user", {})), "字段检查")

    code, _ = request("GET", f"{base}/api/auth/me")
    check("无 token 访问 me 返回 401", code == 401, f"HTTP {code}")

    code, _ = request("GET", f"{base}/api/auth/me", token="not-a-real-token")
    check("伪造 token 返回 401", code == 401, f"HTTP {code}")

    # ---- 5. 修改昵称与密码 ----
    code, patched = request("PATCH", f"{base}/api/auth/me", {"nickname": "改过的昵称"}, token=token)
    check("修改昵称成功", code == 200 and patched.get("user", {}).get("nickname") == "改过的昵称",
          f"HTTP {code}")

    code, _ = request("PATCH", f"{base}/api/auth/me",
                      {"old_password": "bad", "new_password": "NewPass@123"}, token=token)
    check("旧密码错误时拒绝改密（400）", code == 400, f"HTTP {code}")

    new_password = "NewPass@123456"
    code, _ = request("PATCH", f"{base}/api/auth/me",
                      {"old_password": password, "new_password": new_password}, token=token)
    check("旧密码正确时改密成功", code == 200, f"HTTP {code}")
    code, relogin = request("POST", f"{base}/api/auth/login",
                            {"username": username, "password": new_password})
    check("新密码可登录", code == 200, f"HTTP {code}")
    token = relogin.get("access_token", token)

    # ---- 6. 手势上报 ----
    # 语义 id 与 config/gesture_map.json 保持一致（不是模型类别名）
    gestures = ["victory", "point_up", "open_palm", "thumb_up", "cross_fingers", "love_you"]
    saved_ids: list[int] = []
    for index, gesture in enumerate(gestures[:3]):
        code, rep = request("POST", f"{base}/api/records/gesture",
                            {"gesture_type": gesture, "confidence": 0.8 + index * 0.05,
                             "infer_ms": 42.5, "source": "camera"}, token=token)
        ok = code == 201 and rep.get("saved") is True
        check(f"上报 {gesture} 并落库", ok, f"HTTP {code} {rep.get('detail', '')}")
        if ok:
            saved_ids.append(rep["record"]["record_id"])

    # 未登录上报：uid 应为 null，仍然成功
    code, guest = request("POST", f"{base}/api/records/gesture",
                          {"gesture_type": "open_palm", "confidence": 0.9, "source": "images"})
    check("未登录也可上报（uid=null）",
          code == 201 and guest.get("saved") is True and guest["record"]["uid"] is None,
          f"HTTP {code}")

    code, bad = request("POST", f"{base}/api/records/gesture",
                        {"gesture_type": "not_a_gesture", "confidence": 0.5}, token=token)
    check("未知手势类型被拒（422）", code == 422, f"HTTP {code}")

    code, bad = request("POST", f"{base}/api/records/gesture",
                        {"gesture_type": "victory", "confidence": 1.5}, token=token)
    check("置信度越界被拒（422）", code == 422, f"HTTP {code}")

    # 中文名与动作由后端按配置补齐，客户端不需要传
    code, rep = request("POST", f"{base}/api/records/gesture",
                        {"gesture_type": "thumb_up", "confidence": 0.77}, token=token)
    record = rep.get("record") or {}
    check("动作与中文名由后端补齐",
          record.get("action") == "confirm" and record.get("gesture_label") == "点赞",
          f"action={record.get('action')} label={record.get('gesture_label')}")
    if record.get("record_id"):
        saved_ids.append(record["record_id"])

    # ---- 7. 列表与统计 ----
    code, listing = request("GET", f"{base}/api/records/gesture?limit=50", token=token)
    total = listing.get("total", 0)
    check("列表只包含本人记录", code == 200 and total >= 4,
          f"HTTP {code} total={total}")
    check("列表按时间倒序（record_id 递减）",
          [x["record_id"] for x in listing.get("items", [])] == sorted(
              [x["record_id"] for x in listing.get("items", [])], reverse=True),
          f"{len(listing.get('items', []))} 条")

    code, stats = request("GET", f"{base}/api/records/gesture/stats", token=token)
    stats_data = stats.get("stats", {})
    check("统计总数与列表一致", stats_data.get("total") == total,
          f"stats={stats_data.get('total')} list={total}")
    check("统计含按手势分布", bool(stats_data.get("by_type")), str(stats_data.get("by_type")))

    # ---- 8. 删除 ----
    if saved_ids:
        target = saved_ids[0]
        code, _ = request("DELETE", f"{base}/api/records/gesture/{target}", token=token)
        check("删除自己的记录成功", code == 200, f"HTTP {code}")
        code, relist = request("GET", f"{base}/api/records/gesture?limit=50", token=token)
        remaining = [x["record_id"] for x in relist.get("items", [])]
        check("删除后列表不再包含该条", target not in remaining, f"剩余 {len(remaining)} 条")

    code, _ = request("DELETE", f"{base}/api/records/gesture/999999", token=token)
    check("删除不存在的记录返回 404", code == 404, f"HTTP {code}")

    # ---- 9. 越权检查 ----
    other = rand_name("other_")
    code, other_reg = request("POST", f"{base}/api/auth/register",
                              {"username": other, "password": password})
    other_token = other_reg.get("access_token", "")
    if saved_ids[1:]:
        victim = saved_ids[1]
        code, _ = request("DELETE", f"{base}/api/records/gesture/{victim}", token=other_token)
        check("不能删除他人记录（404）", code == 404, f"HTTP {code}")

    code, _ = request("GET", f"{base}/api/admin/overview", token=token)
    check("普通用户访问后台返回 403", code == 403, f"HTTP {code}")

    # ---- 10. 管理员 ----
    code, admin_login = request("POST", f"{base}/api/auth/login",
                                {"username": "admin", "password": "admin123456"})
    if code == 200:
        admin_token = admin_login["access_token"]
        code, ov = request("GET", f"{base}/api/admin/overview", token=admin_token)
        counts = ov.get("counts", {})
        check("管理员可读后台总览", code == 200 and counts.get("users", 0) >= 2,
              f"HTTP {code} users={counts.get('users')} gestures={counts.get('gesture_records')}")
        code, admin_list = request("GET", f"{base}/api/admin/records?limit=5", token=admin_token)
        check("管理员可看全站记录", code == 200 and admin_list.get("total", 0) >= 4,
              f"total={admin_list.get('total')}")
    else:
        check("管理员账号可用（默认 admin/admin123456）", False,
              f"HTTP {code}，若已改密请手动验证")

    # ---- 汇总 ----
    passed = sum(1 for ok, _, _ in results if ok)
    total_cases = len(results)
    print("-" * 72)
    print(f"共 {total_cases} 个用例：通过 {passed}，失败 {total_cases - passed}")
    if passed != total_cases:
        print("\n失败明细：")
        for ok, name, detail in results:
            if not ok:
                print(f"  {FAIL} {name}  ({detail})")
    return 0 if passed == total_cases else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""login：配置/检查元宝网页端登录态（视频号解析需要你自己的元宝账号）。

    login --login    弹出浏览器扫码登录元宝，自动保存 Cookie（需要 playwright）
    login --paste    手动粘贴 Cookie 保存（零依赖，见 README「手动粘贴」）
    login --check    校验已保存的登录态是否有效

stdout 输出一行 JSON 结果；过程提示走 stderr。Cookie 的值永远不会被打印。

退出码：0 正常；1 网络/输入错误；2 playwright 未安装（仅 --login）；3 登录态缺失或失效。
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sphlib import auth, resolve  # noqa: E402

YUANBAO_HOST = "https://yuanbao.tencent.com"
GETUSERINFO = YUANBAO_HOST + "/api/getuserinfo"

EXIT_OK, EXIT_ERROR, EXIT_NO_TOOL, EXIT_NO_LOGIN = 0, 1, 2, 3


def log(msg: str) -> None:
    print(f"[channels-download] {msg}", file=sys.stderr, flush=True)


def err(msg: str) -> None:
    print(f"[channels-download] 错误: {msg}", file=sys.stderr, flush=True)


def _reconfigure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _find_user_id(obj, depth=0):
    """在元宝 getuserinfo 响应里找用户 ID 字段；找不到返回 None。"""
    if depth > 6 or obj is None:
        return None
    if isinstance(obj, dict):
        for key in ("userId", "userid", "user_id", "id"):
            v = obj.get(key)
            if isinstance(v, (str, int)) and str(v).strip():
                return str(v)
        for v in obj.values():
            found = _find_user_id(v, depth + 1)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _find_user_id(v, depth + 1)
            if found:
                return found
    return None


def _userinfo_headers(cookie: str | None) -> dict:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": resolve.USER_AGENT,
        "Origin": YUANBAO_HOST,
        "Referer": YUANBAO_HOST + "/",
        "X-Requested-With": "XMLHttpRequest",
        "X-Source": "web",
        "X-Platform": "mac",
    }
    if cookie:
        headers["Cookie"] = cookie.strip()
    return headers


def check_login(cookie: str, timeout: int = 20) -> dict:
    """校验登录态。返回 {"ok": bool, "reason": str|None, "user_id": 脱敏或 None}。不打印 Cookie。"""
    req = urllib.request.Request(GETUSERINFO, headers=_userinfo_headers(cookie))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.load(resp)
    except urllib.error.HTTPError as e:
        reason = f"登录态失效（HTTP {e.code}）" if e.code in (401, 403) else f"接口返回 HTTP {e.code}"
        return {"ok": False, "reason": reason, "user_id": None}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"ok": False, "reason": f"网络或响应错误: {e}", "user_id": None}

    uid = _find_user_id(body)
    if not uid:
        return {"ok": False, "reason": "接口成功但响应里没有用户信息（可能未登录）", "user_id": None}
    masked = uid[:3] + "***" if len(uid) > 3 else "***"
    return {"ok": True, "reason": None, "user_id": masked}


def cmd_check(args) -> int:
    cookie, source = auth.load_cookie(args.cookie_file)
    if not cookie:
        err(f"没有找到登录态文件: {source}")
        print(json.dumps({"ok": False, "action": "check", "cookie_file": source,
                          "user_id": None, "reason": "登录态未配置（缺少必需字段 hy_user、hy_token）"}, ensure_ascii=False))
        return EXIT_NO_LOGIN

    result = check_login(cookie)
    result.update({"action": "check", "cookie_file": source})
    print(json.dumps(result, ensure_ascii=False))
    if result["ok"]:
        log(f"登录态有效（来源: {source}，用户 {result['user_id']}）")
        return EXIT_OK
    err(f"{result['reason']}（来源: {source}）。请运行 login.py --login 重新扫码")
    return EXIT_NO_LOGIN


def cmd_paste(args) -> int:
    log("请把元宝网页端的 Cookie 整段粘贴进来，然后回车结束：")
    log("获取方法：浏览器打开 yuanbao.tencent.com 并登录 → F12 开发者工具 → Network → 刷新 →")
    log("点任意一个 API 请求 → Request Headers → 复制整行 Cookie 的值。")
    try:
        data = sys.stdin.read()
    except OSError as e:
        err(f"读取输入失败: {e}")
        print(json.dumps({"ok": False, "action": "paste", "reason": f"读取输入失败: {e}"}, ensure_ascii=False))
        return EXIT_ERROR

    cookie = " ".join(data.split())
    if not cookie:
        err("没有读到任何输入")
        print(json.dumps({"ok": False, "action": "paste", "reason": "输入为空"}, ensure_ascii=False))
        return EXIT_NO_LOGIN

    try:
        path = auth.save_cookie(cookie, args.cookie_file)
    except ValueError as e:
        err(str(e))
        print(json.dumps({"ok": False, "action": "paste", "reason": str(e)}, ensure_ascii=False))
        return EXIT_ERROR

    result = check_login(cookie)
    result.update({"action": "paste", "cookie_file": path})
    print(json.dumps(result, ensure_ascii=False))
    if result["ok"]:
        log(f"登录态已保存并验证有效 -> {path}")
        return EXIT_OK
    err(f"Cookie 已保存，但立即校验失败: {result['reason']}。请重新复制完整 Cookie 再试")
    return EXIT_NO_LOGIN


def cmd_login(args) -> int:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        err("未安装 playwright，无法自动扫码。两种办法：")
        err("  a) pip install playwright && playwright install chromium  然后重试 --login")
        err("  b) 零依赖方案：login.py --paste，从浏览器 DevTools 复制 Cookie（见 README）")
        print(json.dumps({"ok": False, "action": "login",
                          "reason": "playwright 未安装，可用 --paste 手动粘贴 Cookie"}, ensure_ascii=False))
        return EXIT_NO_TOOL

    log("即将打开浏览器窗口，请在里面登录腾讯元宝（推荐用微信扫码）…")
    cookie_str = None
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=False)
        except Exception as e:
            err(f"启动 Chromium 失败: {e}")
            err("请先执行: playwright install chromium  （或改用 login.py --paste）")
            print(json.dumps({"ok": False, "action": "login", "reason": f"启动 Chromium 失败: {e}"}, ensure_ascii=False))
            return EXIT_NO_TOOL
        ctx = browser.new_context(user_agent=resolve.USER_AGENT, locale="zh-CN")
        page = ctx.new_page()
        try:
            page.goto(YUANBAO_HOST + "/", timeout=30000)
        except Exception as e:
            err(f"打开元宝页面失败: {e}")
            browser.close()
            print(json.dumps({"ok": False, "action": "login", "reason": f"打开元宝页面失败: {e}"}, ensure_ascii=False))
            return EXIT_ERROR

        log("等待登录成功（最多 5 分钟；登录成功后脚本会自动继续，请勿提前关闭窗口）…")
        deadline = time.time() + 300
        while time.time() < deadline:
            try:
                resp = ctx.request.get(GETUSERINFO, headers=_userinfo_headers(None))
                if resp.ok:
                    if _find_user_id(resp.json()):
                        cookie_str = "; ".join(
                            f"{c['name']}={c['value']}" for c in ctx.cookies(YUANBAO_HOST + "/")
                        )
                        break
            except Exception:
                pass
            page.wait_for_timeout(3000)
        browser.close()

    if not cookie_str:
        err("等待登录超时或未完成。请重试 login.py --login，或改用 login.py --paste")
        print(json.dumps({"ok": False, "action": "login", "reason": "等待登录超时（5 分钟）"}, ensure_ascii=False))
        return EXIT_NO_LOGIN

    try:
        path = auth.save_cookie(cookie_str, args.cookie_file)
    except ValueError as e:
        err(str(e))
        print(json.dumps({"ok": False, "action": "login", "reason": str(e)}, ensure_ascii=False))
        return EXIT_NO_LOGIN

    result = check_login(cookie_str)
    result.update({"action": "login", "cookie_file": path})
    print(json.dumps(result, ensure_ascii=False))
    if result["ok"]:
        log(f"登录态已保存并验证有效 -> {path}")
        return EXIT_OK
    err(f"登录态已保存，但立即校验失败: {result['reason']}")
    return EXIT_NO_LOGIN


def main() -> int:
    _reconfigure_stdio()
    ap = argparse.ArgumentParser(prog="login", description="配置/检查元宝网页端登录态")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--login", action="store_true", help="弹出浏览器扫码登录元宝，自动保存 Cookie")
    g.add_argument("--paste", action="store_true", help="手动粘贴 Cookie 保存")
    g.add_argument("--check", action="store_true", help="校验已保存的登录态是否有效")
    ap.add_argument("--cookie-file", help=f"Cookie 文件路径（默认 {auth.cookie_file()}）")
    args = ap.parse_args()

    if args.login:
        return cmd_login(args)
    if args.paste:
        return cmd_paste(args)
    return cmd_check(args)


if __name__ == "__main__":
    sys.exit(main())

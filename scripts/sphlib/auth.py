# Copyright (c) 2025 ythx-101 — MIT License
# 移植自 https://github.com/ythx-101/sph-download （scripts/sphlib/auth.py），有本地适配：
#   - 默认状态目录改为本 skill 目录下的 .credentials/（不再写 ~/.config）
#   - parse_cookie 容忍换行（从 DevTools / Cookie 编辑器复制时可能带）
#   - 新增 save_cookie()，供 login.py 保存登录态
# 登录态（元宝网页端 Cookie）的位置约定与读取。任何函数都不打印、不返回到日志里 Cookie 的值。

import os
import re

ENV_COOKIE_VALUE = "SPH_YUANBAO_COOKIE"   # 直接放 Cookie 字符串
ENV_COOKIE_FILE = "SPH_COOKIE_FILE"       # Cookie 文件路径
ENV_STATE_DIR = "SPH_STATE_DIR"           # 状态目录（Cookie 文件所在目录）

REQUIRED_FIELDS = ("hy_user", "hy_token")


def _skill_root() -> str:
    # scripts/sphlib/auth.py -> scripts -> skill 根目录
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def state_dir() -> str:
    """状态目录。默认 <skill 根目录>/.credentials，可用环境变量 SPH_STATE_DIR 改。"""
    custom = os.environ.get(ENV_STATE_DIR, "").strip()
    if custom:
        return os.path.abspath(os.path.expanduser(custom))
    return os.path.join(_skill_root(), ".credentials")


def cookie_file(cli_path: str | None = None) -> str:
    """Cookie 文件路径。优先级：命令行参数 > SPH_COOKIE_FILE > <状态目录>/yuanbao.cookie。"""
    for cand in (cli_path, os.environ.get(ENV_COOKIE_FILE, "")):
        if cand and cand.strip():
            return os.path.abspath(os.path.expanduser(cand.strip()))
    return os.path.join(state_dir(), "yuanbao.cookie")


def parse_cookie(cookie_str: str) -> dict:
    """把 Cookie 请求头字符串拆成字典；容忍换行（从 DevTools 或 Cookie 编辑器复制时可能带）。"""
    out = {}
    for item in re.split(r"[;\r\n]+", cookie_str or ""):
        item = item.strip()
        if "=" in item:
            k, v = item.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def load_cookie(cli_path: str | None = None) -> tuple[str | None, str]:
    """返回 (cookie 字符串或 None, 来源描述)。来源描述只含路径或变量名，不含值。"""
    env_val = os.environ.get(ENV_COOKIE_VALUE, "").strip()
    if env_val and not cli_path:
        return env_val, f"环境变量 {ENV_COOKIE_VALUE}"
    path = cookie_file(cli_path)
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            val = f.read().strip()
        if val:
            return val, path
    return None, path


def missing_fields(cookie_str: str) -> list:
    """返回缺少的必需字段名列表（空列表表示齐全）。"""
    cmap = parse_cookie(cookie_str)
    return [k for k in REQUIRED_FIELDS if not cmap.get(k)]


def save_cookie(cookie_str: str, cli_path: str | None = None) -> str:
    """把登录态写入 Cookie 文件（Windows 上尽力收紧权限，失败不阻断）。返回文件路径。"""
    cmap = parse_cookie(cookie_str)
    lacking = [k for k in REQUIRED_FIELDS if not cmap.get(k)]
    if lacking:
        raise ValueError(f"Cookie 缺少必需字段 {'、'.join(lacking)}，请确认从元宝网页端复制")

    path = cookie_file(cli_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(cookie_str.strip() + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # Windows 上 0o600 语义有限，尽力而为
    return path

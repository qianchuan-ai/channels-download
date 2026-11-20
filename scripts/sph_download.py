#!/usr/bin/env python3
"""sph_download：把一条视频号分享链接保存到本地（无外部第三方 API）。

    sph_download <链接或短码> [--out 目录] [--meta-only] [--save-frames] [--max-mb N]

产物在 <输出目录>/<短码>/ 下：
    meta.json    文案、作者、发布时间、互动数、时长、分辨率
    cover.jpg    封面
    video.mp4    视频（已用 ffprobe 校验并抽帧验证）
    frames/      加 --save-frames 时保留 3 张抽帧
    result.json  本次运行的机器可读结果（与 stdout 最后一行相同）

stdout 只输出一行 JSON 结果（供 agent 解析）；人类可读的过程日志全部走 stderr。

退出码：0 成功；1 输入、网络或文件错误；2 没有配置登录态（只存了 meta.json 和 cover.jpg）；
        3 登录态失效，需要重新登录元宝；4 这条链接拿不到视频。

解析逻辑在 sphlib/ 里（移植自 MIT 许可的 ythx-101/sph-download），这个文件只管参数、落盘和提示。
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sphlib import auth, media, resolve  # noqa: E402

EXIT_OK, EXIT_ERROR, EXIT_NO_LOGIN, EXIT_LOGIN_EXPIRED, EXIT_NO_VIDEO = 0, 1, 2, 3, 4


def log(msg: str) -> None:
    print(f"[channels-download] {msg}", file=sys.stderr, flush=True)


def err(msg: str) -> None:
    print(f"[channels-download] 错误: {msg}", file=sys.stderr, flush=True)


def _reconfigure_stdio() -> None:
    # Windows 控制台默认编码可能是 cp936，统一成 UTF-8 避免中文日志炸掉
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def write_meta(out_dir: str, meta: dict) -> str:
    path = os.path.join(out_dir, "meta.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return path


def main() -> int:
    _reconfigure_stdio()

    raw_max_mb = os.environ.get("SPH_MAX_MB", str(media.DEFAULT_MAX_MB))
    try:
        env_max_mb = int(raw_max_mb)
    except ValueError:
        err("环境变量 SPH_MAX_MB 必须是整数（MiB），当前值无效")
        return EXIT_ERROR

    ap = argparse.ArgumentParser(prog="sph_download", description="把一条视频号分享链接保存到本地")
    ap.add_argument("link", help="分享短链、预览页链接、带链接的分享文字或短码")
    ap.add_argument("--out", default="out", help="输出根目录（默认 ./out）")
    ap.add_argument("--cookie-file", help=f"登录态文件（默认 {auth.cookie_file()}，也可用环境变量 {auth.ENV_COOKIE_FILE}）")
    ap.add_argument("--meta-only", action="store_true", help="只取公开元数据和封面，不需要登录态")
    ap.add_argument("--save-frames", action="store_true", help="把 3 张抽帧保留在 frames/ 里")
    ap.add_argument(
        "--max-mb", type=int,
        default=env_max_mb,
        help=f"单个视频大小上限，MiB（默认 {media.DEFAULT_MAX_MB}，可用环境变量 SPH_MAX_MB 改）",
    )
    args = ap.parse_args()

    if args.max_mb <= 0:
        err("--max-mb（或环境变量 SPH_MAX_MB）必须是大于 0 的整数（MiB）")
        return EXIT_ERROR

    lacking_tools = media.require_tools()
    if lacking_tools:
        err(f"缺少命令: {'、'.join(lacking_tools)}，请先安装 ffmpeg（例如 winget install Gyan.FFmpeg）")
        return EXIT_ERROR

    cookie, cookie_source = (None, "") if args.meta_only else auth.load_cookie(args.cookie_file)

    result_json = {"ok": False, "link": args.link, "exit_code": None, "output_dir": None,
                   "video_file": None, "cover_file": None, "meta_file": None, "problem": None, "meta": None}

    # 第一步：解析（纯网络）
    login_problem = None
    video_problem = None
    try:
        short_id = resolve.parse_share_id(args.link)
        log(f"正在解析 {resolve.share_url_of(short_id)}")
        try:
            result = resolve.resolve(short_id, cookie)
        except (resolve.LoginExpiredError, resolve.VideoUnavailableError) as e:
            # 登录态或视频有问题时，公开元数据照样保存
            if isinstance(e, resolve.LoginExpiredError):
                login_problem = f"{e}（登录态来源: {cookie_source}）"
            else:
                video_problem = str(e)
            result = resolve.resolve(short_id, None)
    except resolve.InvalidLinkError as e:
        result_json["problem"] = str(e)
        err(str(e))
        result_json["exit_code"] = EXIT_ERROR
        print(json.dumps(result_json, ensure_ascii=False))
        return EXIT_ERROR
    except (resolve.SphError, OSError) as e:
        result_json["problem"] = f"解析失败: {e}"
        err(f"解析失败: {e}")
        result_json["exit_code"] = EXIT_ERROR
        print(json.dumps(result_json, ensure_ascii=False))
        return EXIT_ERROR

    meta = result.meta
    out_dir = os.path.join(args.out, result.short_id)
    os.makedirs(out_dir, exist_ok=True)
    result_json["output_dir"] = os.path.abspath(out_dir)
    result_json["meta"] = {k: meta.get(k) for k in ("id", "share_url", "description", "author")}

    # 第二步：下载、校验、落盘（临时文件放系统临时目录，结束自动清理）
    with tempfile.TemporaryDirectory(prefix=f"sph_{result.short_id}_") as tmp_dir:
        max_bytes = args.max_mb * 1024 * 1024
        try:
            if result.cover_url:
                tmp_cover = os.path.join(tmp_dir, "cover.jpg")
                media.download(result.cover_url, tmp_cover, max_bytes)
                media.probe(tmp_cover)
                shutil.move(tmp_cover, os.path.join(out_dir, "cover.jpg"))
                meta["cover_file"] = "cover.jpg"
                result_json["cover_file"] = os.path.abspath(os.path.join(out_dir, "cover.jpg"))

            if result.video_url:
                tmp_video = os.path.join(tmp_dir, "video.mp4")
                size = media.download(result.video_url, tmp_video, max_bytes)
                info = media.summarize_video(media.probe(tmp_video))
                frames_dir = os.path.join(out_dir, "frames") if args.save_frames else os.path.join(tmp_dir, "frames")
                frames = media.extract_frames(tmp_video, info["duration"] or 0.0, frames_dir)
                dst_video = os.path.join(out_dir, "video.mp4")
                shutil.move(tmp_video, dst_video)
                meta["duration"] = info["duration"]
                meta["video_file"] = "video.mp4"
                meta["video"] = dict(info, size_bytes=size, verified_frames=len(frames))
                result_json["video_file"] = os.path.abspath(dst_video)
                log(
                    f"视频已保存 -> {dst_video}（{info['duration']}s，{info['width']}x{info['height']}，"
                    f"{size / 1048576:.1f} MiB，抽帧验证 {len(frames)} 帧）"
                )
        except (media.SizeLimitExceededError, media.MediaError, OSError, subprocess.CalledProcessError) as e:
            result_json["problem"] = f"下载或校验失败: {e}"
            result_json["meta_file"] = os.path.abspath(write_meta(out_dir, meta))
            err(f"下载或校验失败: {e}")
            result_json["exit_code"] = EXIT_ERROR
            result_json["output_dir"] = os.path.abspath(out_dir)
            result_json["meta"] = {k: meta.get(k) for k in ("id", "share_url", "description", "author")}
            print(json.dumps(result_json, ensure_ascii=False))
            return EXIT_ERROR

    result_json["meta_file"] = os.path.abspath(write_meta(out_dir, meta))
    log(f"元数据已保存 -> {result_json['meta_file']}")

    if meta["video_file"]:
        result_json["ok"] = True
    elif args.meta_only:
        result_json["ok"] = True

    if result_json["ok"]:
        result_json["exit_code"] = EXIT_OK
        print(json.dumps(result_json, ensure_ascii=False))
        return EXIT_OK

    if login_problem:
        result_json["problem"] = login_problem
        result_json["exit_code"] = EXIT_LOGIN_EXPIRED
        err(f"{login_problem}。已保存公开元数据和封面。请重新登录元宝网页端（login.py --login）。（退出码 {EXIT_LOGIN_EXPIRED}）")
    elif video_problem:
        result_json["problem"] = video_problem
        result_json["exit_code"] = EXIT_NO_VIDEO
        err(f"{video_problem}。已保存公开元数据和封面。（退出码 {EXIT_NO_VIDEO}）")
    else:
        result_json["problem"] = f"没有找到登录态（{cookie_source}）"
        result_json["exit_code"] = EXIT_NO_LOGIN
        err(
            f"没有找到登录态（{cookie_source}），只保存了公开元数据和封面。"
            f"请先运行 login.py --login 扫码，或 login.py --paste 粘贴 Cookie。（退出码 {EXIT_NO_LOGIN}）"
        )

    print(json.dumps(result_json, ensure_ascii=False))
    return result_json["exit_code"]


if __name__ == "__main__":
    sys.exit(main())

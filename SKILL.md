---
name: channels-download
description: 视频号下载：本地解析视频号分享链接并保存 MP4。Download WeChat Channels (视频号) videos locally from a share link. Use when the user asks to download a 视频号/Channels video, extract its cover/metadata, or save a shared sph link locally (视频号下载、微信视频号、sph 链接、weixin.qq.com/sph).
---

# 视频号下载（channels-download）

Fully local: a Python CLI in this skill resolves a WeChat Channels share link into a playable MP4 using **your own Tencent Yuanbao (元宝) web login state** stored under `.credentials/`. No third-party parsing API, no proxy certificate, no WeChat client hook. 腾讯元宝接口变动可能导致失效；失效时报错即可，不要绕路接外部服务。

## When to use

User sends a 视频号 share link / preview link / share text / bare short code and wants the video saved locally. Supported inputs:
- `https://weixin.qq.com/sph/<短码>`（含整段分享文字，保留原样传入）
- `https://channels.weixin.qq.com/finder-preview/pages/sph?id=...`
- 裸短码（6–32 位字母数字）

Private/deleted videos, image-only notes, live streams, and expired share tokens may fail — say so honestly rather than retrying blindly.

## One-time credential

Resolution requires the user's own Yuanbao login cookie (hy_user/hy_token), saved at `<skill 根目录>/.credentials/yuanbao.cookie` (never read aloud, never logged, never sent anywhere except yuanbao.tencent.com / channels.weixin.qq.com in these requests).

- **First use or expiry**: run `python <skill>/scripts/login.py --login` (opens a browser, user scans QR with WeChat; needs playwright + chromium) — walk the user through it. Zero-dependency fallback: `login.py --paste` (user pastes cookie from browser DevTools).
- **Verify anytime**: `python <skill>/scripts/login.py --check`.
- Cookie 过期（退出码 3）时明确告知并引导重新登录；绝不假装下载成功，绝不自动重试解析超过一次。

## Workflow

### 1. Run the download

Use an absolute output directory (the task's output directory when the user doesn't specify one):

```sh
python <skill>/scripts/sph_download.py "<用户发来的链接或整段分享文字>" --out "<输出目录>"
```

- stdout 最后是一行 JSON（`ok`/`exit_code`/`output_dir`/`video_file`/`meta_file`/`problem`）；过程日志在 stderr。
- Useful flags: `--save-frames`（保留 3 张验证抽帧）、`--meta-only`（只要元数据/封面，无需登录态）、`--max-mb`（默认 200 MiB）。
- Requires `ffmpeg`/`ffprobe` on PATH.

### 2. Interpret the exit code

| Exit code | Meaning | What to tell the user |
| --- | --- | --- |
| 0 | 成功 | 本地 MP4 路径 + 元数据（作者/文案/时长/分辨率），简明交付 |
| 1 | 输入无效、网络或校验失败 | 报 `problem`；链接无效时请用户重新复制分享链接 |
| 2 | 未配置登录态 | 引导 `login.py --login` 或 `--paste`；说明公开元数据已存 |
| 3 | 登录态失效 | 引导重新扫码；不自动重试 |
| 4 | 链接拿不到视频（已删除/图文/受限） | 如实转述 `problem`，不要反复重试 |

### 3. Deliver

Report the absolute local path, file size, duration, and author/description from the JSON. 产物为原始视频流，天然无水印，但不承诺特定分辨率或转码。`meta.json`/`cover.jpg` 一并告知位置。

## Boundaries

- 串行使用，一次一条；批量时逐条顺序处理。
- 解析出的视频直链有时效——脚本内已即时下载，不要把直链当作交付物返回给用户。
- 只做个人归档用途；不下私密/受限内容，不二次分发。尊重内容作者版权。
- 不修改服务器、不调用任何第三方解析 API、不安装其他下载器来"绕过"失败。失败就是失败，如实报告。

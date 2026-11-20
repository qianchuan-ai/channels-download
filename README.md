# channels-download — 视频号下载（本地复刻版）

把一条微信视频号分享链接解析并保存为本地 MP4。**不接任何第三方解析 API**：解析走腾讯自有端点（`yuanbao.tencent.com` 用你自己的元宝登录态、`channels.weixin.qq.com` 预览接口、`finder.video.qq.com` CDN），登录态只存在本目录 `.credentials/` 里。

> 原理与代码移植自 MIT 许可的 [ythx-101/sph-download](https://github.com/ythx-101/sph-download)（思路来源 [ltaoo/wx_channels_download](https://github.com/ltaoo/wx_channels_download)），见 LICENSE。

## 环境要求

- Python 3.10+（仅标准库，无需 pip install）
- `ffmpeg` / `ffprobe` 在 PATH 上（校验与抽帧用）
- 自动扫码登录（可选）：`playwright` + Chromium；不想装就用「手动粘贴」方式

安装 ffmpeg：优先 `winget install Gyan.FFmpeg`；若 GitHub 下载被墙，可从 npmmirror 取静态构建（含 ffmpeg + ffprobe 两个 exe，放进 PATH 目录即可）：

```sh
# ffmpeg 6.1.1 (gyan essentials, npmmirror CDN)
curl -L -o ffmpeg.gz  https://registry.npmmirror.com/-/binary/ffmpeg-static/b6.1.1/ffmpeg-win32-x64.gz
curl -L -o ffprobe.gz https://registry.npmmirror.com/-/binary/ffmpeg-static/b6.1.1/ffprobe-win32-x64.gz
gunzip -c ffmpeg.gz > ffmpeg.exe; gunzip -c ffprobe.gz > ffprobe.exe
```

## 首次使用：配置元宝登录态

视频号的公开预览页只返回封面，**视频地址必须用你自己的元宝账号登录态换取**（一次性，约 30 秒）：

### 方式 A：自动扫码（推荐）

```sh
pip install playwright
playwright install chromium
python scripts/login.py --login
```

脚本会打开元宝网页，用微信扫码登录即可；登录成功后自动保存 Cookie 并校验。

### 方式 B：手动粘贴（零依赖）

1. 浏览器打开 `https://yuanbao.tencent.com/` 并登录（微信扫码即可）
2. F12 → Network → 刷新页面 → 点任意一个 API 请求 → Request Headers → 复制整行 `Cookie` 的值
3. 运行 `python scripts/login.py --paste`，把 Cookie 整段粘贴进去回车

### 校验

```sh
python scripts/login.py --check
```

Cookie 会过期（退出登录、元宝侧清理等）。过期时重新执行一次上面的登录流程即可。

## 日常使用

```sh
python scripts/sph_download.py "https://weixin.qq.com/sph/xxxxxx" --out D:/downloads
```

支持整段分享文字（不用手工清洗）、预览页链接、裸短码。产物在 `<out>/<短码>/` 下：

| 文件 | 说明 |
| --- | --- |
| `video.mp4` | 视频（ffprobe 校验 + 3 帧抽帧验证后才会落盘） |
| `meta.json` | 作者、文案、发布时间、互动数、时长、分辨率、字节数 |
| `cover.jpg` | 封面 |
| `result.json` | 机器可读结果（与脚本 stdout 最后一行相同） |
| `frames/` | 仅 `--save-frames` |

常用参数：`--meta-only`（无需登录态，只取公开元数据）、`--save-frames`、`--max-mb 200`（单文件上限，MiB）。

## 退出码

| 码 | 含义 |
| --- | --- |
| 0 | 成功 |
| 1 | 链接无效、网络错误、下载或校验失败 |
| 2 | 未配置登录态（已保存公开元数据和封面） |
| 3 | 登录态失效，请重新登录元宝 |
| 4 | 这条链接拿不到视频（已删除 / 纯图文 / 受限） |

## 故障排查

| 现象 | 处理 |
| --- | --- |
| `缺少命令: ffmpeg、ffprobe` | 安装 ffmpeg 并确保在 PATH 上 |
| 退出码 3 / `登录态已失效` | `login.py --login` 重扫；或 `--paste` 重新粘贴 |
| 退出码 4 | 链接对应内容确实拿不到，换一条可正常打开的链接试试 |
| 接口返回字段变化导致解析失败 | 上游 sph-download 可能已跟进修复，可对照其仓库更新 `scripts/sphlib/` |

## 已知边界

- 元宝接口或预览页行为变化时可能失效（腾讯单方面改动，属预期内风险）。
- 私密、已删除、仅图文、直播回放等拿不到视频。
- 解析出的视频直链有时效；脚本内已即时下载，请勿把它当作长期可用的直链。
- 仅限个人归档自己有权访问的内容；请尊重内容作者版权，勿二次分发。

#!/usr/bin/env node
/**
 * channels-download DSH 插件入口
 *
 * 包装 Python CLI，提供简洁的命令行接口。
 * 实际下载逻辑由 scripts/sph_download.py 执行。
 */

import { execSync } from 'child_process';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import { existsSync } from 'fs';

// __dirname in ESM requires this pattern
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// scripts/ 在 src/ 的上一级
const ROOT_DIR = join(__dirname, '..');
const PYTHON = process.platform === 'win32' ? 'python' : 'python3';
const SCRIPTS_DIR = join(ROOT_DIR, 'scripts');
const SPH_SCRIPT = join(SCRIPTS_DIR, 'sph_download.py');
const LOGIN_SCRIPT = join(SCRIPTS_DIR, 'login.py');

function runPython(script, args = []) {
  const cmd = [PYTHON, script, ...args].join(' ');
  return execSync(cmd, {
    stdio: 'inherit',
    encoding: 'utf-8',
    shell: true
  });
}

function printHelp() {
  console.log(`
channels-download — 视频号下载 DSH 插件

用法:
  channels-download <链接或短码> [--out <目录>] [--meta-only] [--save-frames]
  channels-download login [--login|--paste|--check]
  channels-download download <链接> --out <目录>

选项:
  --out        输出目录（默认 ./out）
  --meta-only  只获取公开元数据和封面，无需登录态
  --save-frames 保留 3 张验证抽帧

凭据管理:
  login --login    扫码登录元宝（需要 playwright）
  login --paste    手动粘贴 Cookie
  login --check    校验登录态

退出码:
  0 成功
  1 输入/网络错误
  2 未配置登录态
  3 登录态失效
  4 链接拿不到视频

示例:
  channels-download "https://weixin.qq.com/sph/AOlmtNwt4y"
  channels-download "AvmYweU3hv" --out ./downloads
  channels-download login --login
`);
}

function checkDependencies() {
  const missing = [];
  try {
    execSync(`${PYTHON} --version`, { stdio: 'ignore' });
  } catch {
    missing.push('Python 3.10+');
  }
  try {
    execSync('ffprobe -version', { stdio: 'ignore' });
  } catch {
    missing.push('ffmpeg/ffprobe');
  }
  if (missing.length > 0) {
    console.error(`缺少依赖: ${missing.join(', ')}`);
    console.error('请安装后重试。');
    process.exit(1);
  }
}

function main() {
  const [cmd, ...args] = process.argv.slice(2);

  if (!cmd || cmd === '--help' || cmd === '-h') {
    printHelp();
    process.exit(0);
  }

  if (cmd === 'download' || cmd === 'dl' || cmd === 'run') {
    // 默认行为：下载视频
    runPython(SPH_SCRIPT, args);
  } else if (cmd === 'login') {
    // 登录/管理凭据
    runPython(LOGIN_SCRIPT, args);
  } else if (cmd === 'check') {
    runPython(LOGIN_SCRIPT, ['--check', ...args]);
  } else {
    // 直接透传给 sph_download.py
    runPython(SPH_SCRIPT, [cmd, ...args]);
  }
}

// 检查依赖
checkDependencies();
main();

export { runPython, main };

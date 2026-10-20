/**
 * 截屏链路自检：真浏览器里跑一次 captureViewport，读回实测指标。
 *
 * 为什么不用 `chrome --dump-dom`：headless 的 `--dump-dom` 在 load 后（或虚拟时间耗尽时）
 * 立刻 dump，而 html2canvas 的渲染要等真实帧，dump 常常拿到"还在截屏"的中间态。
 * 这里用 CDP 连上去主动轮询页面状态，截完才读，稳定可重复。
 *
 * 前置：静态服务已启动（页面和 SDK 走 http，不能是 file://）
 *     .venv/Scripts/python -m http.server 8080 --bind 127.0.0.1 --directory .
 *
 * 用法：
 *     node scripts/check_screenshot.mjs
 *     node scripts/check_screenshot.mjs --browser "C:/Program Files/Google/Chrome/Application/chrome.exe"
 *     node scripts/check_screenshot.mjs --page-url http://127.0.0.1:8080/frontend/pages/selfcheck.html
 *
 * 退出码 0 表示截屏链路可用。
 */

import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const PASS = '✅';
const FAIL = '❌';

const CANDIDATES = [
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
  '/usr/bin/chromium-browser',
];

function parseArgs() {
  const args = { pageUrl: 'http://127.0.0.1:8080/frontend/pages/selfcheck.html', browser: null, port: 9333 };
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--page-url') args.pageUrl = argv[++i];
    else if (argv[i] === '--browser') args.browser = argv[++i];
    else if (argv[i] === '--port') args.port = Number(argv[++i]);
  }
  return args;
}

function findBrowser(explicit) {
  if (explicit) return existsSync(explicit) ? explicit : null;
  return CANDIDATES.find((p) => existsSync(p)) || null;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitFor(check, { timeout = 20000, interval = 200, label = '条件' } = {}) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const value = await check();
    if (value) return value;
    await sleep(interval);
  }
  throw new Error(`等待${label}超时（${timeout}ms）`);
}

/** 极简 CDP 客户端：只用到 Runtime.evaluate，够本脚本用，不引第三方库 */
function connect(wsUrl) {
  const ws = new WebSocket(wsUrl);
  let seq = 0;
  const pending = new Map();

  ws.addEventListener('message', (event) => {
    let msg;
    try {
      msg = JSON.parse(event.data);
    } catch {
      return;
    }
    const resolver = pending.get(msg.id);
    if (!resolver) return;
    pending.delete(msg.id);
    if (msg.error) resolver.reject(new Error(msg.error.message || 'CDP 调用失败'));
    else resolver.resolve(msg.result);
  });

  const ready = new Promise((resolve, reject) => {
    ws.addEventListener('open', () => resolve(), { once: true });
    ws.addEventListener('error', () => reject(new Error('CDP WebSocket 连接失败')), { once: true });
  });

  function send(method, params = {}) {
    const id = ++seq;
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params }));
    });
  }

  return { ready, send, close: () => ws.close() };
}

async function evaluate(client, expression) {
  const result = await client.send('Runtime.evaluate', {
    expression,
    returnByValue: true,
    awaitPromise: true,
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.text || '页面脚本异常');
  }
  return result.result?.value;
}

async function main() {
  const args = parseArgs();
  const browser = findBrowser(args.browser);
  if (!browser) {
    console.log(`${FAIL} 没找到 Chrome / Edge。请用 --browser 指定，或手动打开自检页：`);
    console.log(`   ${args.pageUrl}`);
    return 2;
  }
  console.log(`浏览器：${browser}`);
  console.log(`自检页：${args.pageUrl}`);
  console.log('-'.repeat(72));

  const profile = mkdtempSync(join(tmpdir(), 'gwc-shot-'));
  const child = spawn(
    browser,
    [
      '--headless=new',
      '--disable-gpu',
      '--no-sandbox',
      '--no-first-run',
      '--disable-extensions',
      `--remote-debugging-port=${args.port}`,
      `--user-data-dir=${profile}`,
      '--window-size=1280,720',
      'about:blank',
    ],
    { stdio: 'ignore' },
  );

  let client = null;
  try {
    // 等调试端口就绪
    const target = await waitFor(
      async () => {
        try {
          const res = await fetch(`http://127.0.0.1:${args.port}/json/new?${encodeURIComponent(args.pageUrl)}`, {
            method: 'PUT',
          });
          if (!res.ok) return null;
          const info = await res.json();
          return info.webSocketDebuggerUrl ? info : null;
        } catch {
          return null;
        }
      },
      { timeout: 25000, interval: 300, label: '浏览器调试端口' },
    );

    client = connect(target.webSocketDebuggerUrl);
    await client.ready;
    await client.send('Runtime.enable');
    await client.send('Page.enable');

    // 主动轮询状态：截完才读，避免拿到中间态
    const payload = await waitFor(
      async () => {
        const text = await evaluate(client, "document.getElementById('status')?.textContent || ''");
        if (!text.startsWith('CHECK ')) return null;
        try {
          return JSON.parse(text.slice(6));
        } catch {
          return null;
        }
      },
      { timeout: 60000, interval: 300, label: '截屏结果' },
    );

    const checks = [];
    const check = (name, ok, detail = '') => {
      checks.push({ ok, name, detail });
      console.log(`${ok ? PASS : FAIL} ${name}${detail ? `  (${detail})` : ''}`);
    };

    if (!payload.ok) {
      console.log(`${FAIL} 截屏失败：${payload.error}`);
      return 1;
    }

    const { width = 0, height = 0, cssWidth = 0, cssHeight = 0, colors = 0, avg = 0, ms = 0, bytes = 0 } = payload;
    check('截屏成功返回', true, `${width}×${height}px / ${(bytes / 1024).toFixed(0)}KB`);
    check('尺寸等于视口（scale=1）', width === cssWidth && height === cssHeight, `视口 ${cssWidth}×${cssHeight}`);
    check('图片不是空白（颜色数 > 20）', colors > 20, `colors=${colors}`);
    // 白底页面亮度本来就高，这里只排除"整张全黑 / 整张过曝"两种明显异常
    check('平均亮度正常（15~252）', avg >= 15 && avg <= 252, `avg=${avg}`);
    check('截取耗时 < 3000ms（需求 6.1 上限）', ms < 3000, `${ms}ms`);

    console.log('-'.repeat(72));
    const passed = checks.filter((c) => c.ok).length;
    console.log(`${passed === checks.length ? PASS : FAIL} ${passed}/${checks.length} 通过`);
    return passed === checks.length ? 0 : 1;
  } catch (err) {
    console.log(`${FAIL} ${err.message}`);
    return 1;
  } finally {
    try {
      if (client) {
        await client.send('Browser.close').catch(() => {});
        client.close();
      }
    } catch {
      /* 关闭失败无所谓，下面还会 kill */
    }
    child.kill();
    // Windows 下文件句柄可能还没释放，删不掉就算了（临时目录会被系统清理）
    try {
      rmSync(profile, { recursive: true, force: true });
    } catch {
      /* ignore */
    }
  }
}

process.exit(await main());

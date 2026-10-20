/**
 * 嵌入示例页自检：证明"别的页面接 9 行代码就能用手势"。
 *
 * 这台机器没有摄像头，所以脚本走「用示例图」这条路：SDK 会依次把 4 张手势图
 * 当作帧来源，和真实摄像头的处理路径完全一致（FrameSource 只是换了个取帧实现）。
 *
 * 断言的重点不是"识别准不准"，而是：
 *   - 宿主页面除了 9 行接入代码外没做任何事，动作却真的执行了；
 *   - 触发 → 动作 → 统计这条链路在嵌入场景下依然成立（这套代码已在 M1 单测过，
 *     这里验的是"脱离演示页之后还成立"）。
 *
 * 前置：后端 + 静态服务在跑（scripts/start_dev.py）
 *
 * 用法：
 *     node scripts/check_embed.mjs
 *     node scripts/check_embed.mjs --screenshot data/embed.png
 *
 * 退出码 0 表示嵌入链路可用。
 */

import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';

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
];

function parseArgs() {
  const args = {
    pageUrl: 'http://127.0.0.1:8080/frontend/pages/embed-demo.html',
    apiBase: 'http://127.0.0.1:8000',
    browser: null,
    port: 9335,
    screenshot: null,
    timeout: 90000,
  };
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i += 1) {
    const key = argv[i];
    if (key === '--page-url') args.pageUrl = argv[++i];
    else if (key === '--api-base') args.apiBase = argv[++i];
    else if (key === '--browser') args.browser = argv[++i];
    else if (key === '--port') args.port = Number(argv[++i]);
    else if (key === '--screenshot') args.screenshot = argv[++i];
    else if (key === '--timeout') args.timeout = Number(argv[++i]);
  }
  args.apiBase = args.apiBase.replace(/\/+$/, '');
  return args;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitFor(check, { timeout = 20000, interval = 250, label = '条件' } = {}) {
  const deadline = Date.now() + timeout;
  let lastError = null;
  while (Date.now() < deadline) {
    try {
      const value = await check();
      if (value) return value;
    } catch (err) {
      lastError = err; // 导航/切源瞬间 context 可能重建，重试即可
    }
    await sleep(interval);
  }
  throw new Error(`等待${label}超时（${timeout}ms）${lastError ? `：${lastError.message}` : ''}`);
}

function connect(wsUrl) {
  const ws = new WebSocket(wsUrl);
  let seq = 0;
  const pending = new Map();
  const exceptions = [];

  ws.addEventListener('message', (event) => {
    let msg;
    try {
      msg = JSON.parse(event.data);
    } catch {
      return;
    }
    if (msg.method === 'Runtime.exceptionThrown') {
      const d = msg.params?.exceptionDetails;
      exceptions.push(d?.exception?.description || d?.text || '未知异常');
      return;
    }
    const resolver = pending.get(msg.id);
    if (!resolver) return;
    pending.delete(msg.id);
    if (msg.error) resolver.reject(new Error(msg.error.message || 'CDP 调用失败'));
    else resolver.resolve(msg.result);
  });

  const ready = new Promise((resolve0, reject) => {
    ws.addEventListener('open', () => resolve0(), { once: true });
    ws.addEventListener('error', () => reject(new Error('CDP WebSocket 连接失败')), { once: true });
  });

  function send(method, params = {}) {
    const id = ++seq;
    return new Promise((resolve0, reject) => {
      pending.set(id, { resolve: resolve0, reject });
      ws.send(JSON.stringify({ id, method, params }));
    });
  }

  return { ready, send, exceptions, close: () => ws.close() };
}

async function evaluate(client, expression) {
  const result = await client.send('Runtime.evaluate', {
    expression,
    returnByValue: true,
    awaitPromise: true,
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text || '页面脚本异常');
  }
  return result.result?.value;
}

async function main() {
  const args = parseArgs();
  const browser = args.browser && existsSync(args.browser) ? args.browser : CANDIDATES.find((p) => existsSync(p));
  if (!browser) {
    console.log(`${FAIL} 没找到 Chrome / Edge，无法自动自检。手动打开验证：`);
    console.log(`   ${args.pageUrl} → 点「用示例图」`);
    return 2;
  }
  console.log(`浏览器：${browser}`);
  console.log(`嵌入页：${args.pageUrl}`);
  console.log(`接口：  ${args.apiBase}`);
  console.log('-'.repeat(72));

  const profile = mkdtempSync(join(tmpdir(), 'gwc-embed-'));
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
      '--window-size=1280,900',
      'about:blank',
    ],
    { stdio: 'ignore' },
  );

  const checks = [];
  const check = (name, ok, detail = '') => {
    checks.push({ ok, name, detail });
    console.log(`${ok ? PASS : FAIL} ${name}${detail ? `  (${detail})` : ''}`);
  };

  let client = null;
  try {
    const target = await waitFor(
      async () => {
        try {
          const res = await fetch(
            `http://127.0.0.1:${args.port}/json/new?${encodeURIComponent(args.pageUrl)}`,
            { method: 'PUT' },
          );
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

    // 页面里的接口地址走 localStorage（auth.js 的约定），先对齐再点按钮
    await waitFor(
      async () => evaluate(client, "document.readyState === 'complete' && !!window.__gwcEmbed"),
      { timeout: 30000, label: '页面加载' },
    );
    await evaluate(
      client,
      `localStorage.setItem('gwc_endpoint', ${JSON.stringify(args.apiBase)}), true`,
    );

    const initial = await evaluate(client, 'window.__gwcEmbed.snapshot()');
    check('页面加载后处于未启动状态', initial.running === false && /准备中/.test(initial.status), initial.status);

    // ---- 用示例图启动（等价于宿主页调用 ctrl.start） ----
    await evaluate(client, "document.getElementById('btnImages').click(), true");
    const started = await waitFor(
      async () => {
        const snap = await evaluate(client, 'window.__gwcEmbed.snapshot()');
        if (snap.running && /运行中/.test(snap.status)) return snap;
        if (snap.logs.some((l) => l.includes('失败'))) return { failed: snap };
        return null;
      },
      { timeout: 30000, label: '示例图启动' },
    );
    if (started.failed) {
      check('示例图能启动识别', false, started.failed.logs.find((l) => l.includes('失败')));
      throw new Error('示例图启动失败，后面的断言没有意义');
    }
    check('示例图能启动识别', true, started.status);

    // ---- 等一次触发 + 动作执行 ----
    // 4 张图 × 1.5s，加上 3 帧防抖，正常 10s 内必然出现触发
    const afterTrigger = await waitFor(
      async () => {
        const snap = await evaluate(client, 'window.__gwcEmbed.snapshot()');
        const triggered = snap.logs.some((l) => l.includes('触发'));
        const acted = snap.logs.some((l) => l.includes('动作「'));
        return triggered && acted ? snap : null;
      },
      { timeout: args.timeout, interval: 400, label: '手势触发与动作执行' },
    );
    check('宿主页收到手势触发', true, afterTrigger.logs.find((l) => l.includes('触发')));

    // 不预设"一定触发哪个手势"——模型对同一张图的判断会随 SDK 的缩放/裁剪而变，
    // 断言只关心"触发了之后默认动作确实执行了"，这才是嵌入能力的关键
    const actionLines = afterTrigger.logs.filter((l) => l.includes('动作「'));
    const doneActions = actionLines.filter((l) => l.includes('完成'));
    check('默认动作被执行（无需业务代码）', doneActions.length > 0, doneActions[0] || actionLines[0]);
    const screenshotted = actionLines.some((l) => l.includes('截屏'));
    check(
      '截屏动作产生了截图',
      !screenshotted || afterTrigger.stats.screenshots > 0,
      screenshotted ? `${afterTrigger.stats.screenshots} 张` : '本轮没触发截屏类手势',
    );

    // 🤟 那张图会额外走一次图片识别（截图 → 上传 → 识别）
    const recognized = await waitFor(
      async () => {
        const snap = await evaluate(client, 'window.__gwcEmbed.snapshot()');
        return snap.stats.recognitions > 0 ? snap : null;
      },
      { timeout: args.timeout, interval: 400, label: '🤟 图片识别' },
    ).catch(() => null);
    check(
      '🤟 触发了图片识别（截屏 + AI 搜索链路）',
      Boolean(recognized),
      recognized ? `${recognized.stats.recognitions} 次` : '没等到（示例图里 🤟 的置信度可能偏低）',
    );

    const snapMid = await evaluate(client, 'window.__gwcEmbed.snapshot()');
    check('识别帧数在增长', snapMid.stats.frames > 5, `${snapMid.stats.frames} 帧`);
    check(
      '单帧推理耗时在预期范围（< 3s）',
      snapMid.stats.lastInferMs > 0 && snapMid.stats.lastInferMs < 3000,
      `${Math.round(snapMid.stats.lastInferMs)}ms`,
    );

    // ---- 停止 ----
    await evaluate(client, "document.getElementById('btnStop').click(), true");
    const stopped = await waitFor(
      async () => {
        const s = await evaluate(client, 'window.__gwcEmbed.snapshot()');
        return s.running === false ? s : null;
      },
      { timeout: 15000, label: '停止' },
    );
    check('停止后识别循环确实停了', stopped.running === false && /已停止/.test(stopped.status), stopped.status);

    // ---- 页面自身没问题 ----
    const realErrors = client.exceptions.filter((e) => !/favicon|ERR_/i.test(e));
    check('页面无未捕获异常', realErrors.length === 0, realErrors.slice(0, 2).join(' | '));

    if (args.screenshot) {
      await evaluate(client, 'window.scrollTo(0, 0), true');
      await sleep(300);
      const shot = await client.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
      const out = resolve(args.screenshot);
      mkdirSync(dirname(out), { recursive: true });
      writeFileSync(out, Buffer.from(shot.data, 'base64'));
      console.log(`截图：${out}`);
    }

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
      /* ignore */
    }
    child.kill();
    try {
      rmSync(profile, { recursive: true, force: true });
    } catch {
      /* Windows 句柄未释放，交给系统清理 */
    }
  }
}

process.exit(await main());

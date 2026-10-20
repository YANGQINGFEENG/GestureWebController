/**
 * 后台管理页自检：真浏览器里跑一遍登录 → 统计 → 用户表 → 三个记录 tab。
 *
 * 为什么要浏览器自检：接口测试只能证明"数据拿得到"，证明不了
 * "页面把 null 渲染成 null"、tab 切了但表格没换、缩略图 404 这类前端问题。
 * 这些只有真渲染一次才看得见。
 *
 * 前置：后端 + 静态服务都在跑（scripts/start_dev.py 一条命令起两个）
 *
 * 用法：
 *     node scripts/check_admin.mjs
 *     node scripts/check_admin.mjs --admin-user admin --admin-pass admin123456
 *     node scripts/check_admin.mjs --browser "C:/Program Files/Google/Chrome/Application/chrome.exe"
 *     node scripts/check_admin.mjs --screenshot data/admin.png   # 顺便存一张整页截图
 *
 * 退出码 0 表示后台页面可用。
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
  const args = {
    pageUrl: 'http://127.0.0.1:8080/frontend/pages/admin.html',
    apiBase: 'http://127.0.0.1:8000',
    adminUser: process.env.GWC_ADMIN_USER || 'admin',
    adminPass: process.env.GWC_ADMIN_PASSWORD || 'admin123456',
    browser: null,
    port: 9334,
    screenshot: null,
  };
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i += 1) {
    const key = argv[i];
    if (key === '--page-url') args.pageUrl = argv[++i];
    else if (key === '--api-base') args.apiBase = argv[++i];
    else if (key === '--admin-user') args.adminUser = argv[++i];
    else if (key === '--admin-pass') args.adminPass = argv[++i];
    else if (key === '--browser') args.browser = argv[++i];
    else if (key === '--port') args.port = Number(argv[++i]);
    else if (key === '--screenshot') args.screenshot = argv[++i];
  }
  args.apiBase = args.apiBase.replace(/\/+$/, '');
  return args;
}

function findBrowser(explicit) {
  if (explicit) return existsSync(explicit) ? explicit : null;
  return CANDIDATES.find((p) => existsSync(p)) || null;
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
      lastError = err; // 导航瞬间 context 会被销毁，重试即可
    }
    await sleep(interval);
  }
  throw new Error(`等待${label}超时（${timeout}ms）${lastError ? `：${lastError.message}` : ''}`);
}

/** 极简 CDP 客户端：Runtime.evaluate + 收集页面 JS 异常 */
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
  const browser = findBrowser(args.browser);
  if (!browser) {
    console.log(`${FAIL} 没找到 Chrome / Edge。请用 --browser 指定，或手动打开：`);
    console.log(`   ${args.pageUrl}（账号 ${args.adminUser}）`);
    return 2;
  }
  console.log(`浏览器：${browser}`);
  console.log(`后台页：${args.pageUrl}`);
  console.log(`接口：  ${args.apiBase}`);
  console.log('-'.repeat(72));

  const profile = mkdtempSync(join(tmpdir(), 'gwc-admin-'));
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
      '--window-size=1400,900',
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

    // ---- 1. 未登录态 ----
    await waitFor(
      async () => evaluate(client, "document.readyState === 'complete' && !!document.getElementById('authCard')"),
      { timeout: 30000, label: '页面加载' },
    );
    const anon = await evaluate(
      client,
      `({
        authVisible: !document.getElementById('authCard').classList.contains('hidden'),
        panelHidden: document.getElementById('panel').classList.contains('hidden'),
        who: document.getElementById('who').textContent.trim()
      })`,
    );
    check('未登录时显示登录卡片、隐藏面板', anon.authVisible && anon.panelHidden, `who=${anon.who}`);

    // ---- 2. 登录 ----
    const base = await evaluate(
      client,
      `(() => {
        const cur = (localStorage.getItem('gwc_endpoint') || 'http://127.0.0.1:8000').replace(/\\/+$/, '');
        localStorage.setItem('gwc_endpoint', ${JSON.stringify(args.apiBase)});
        return cur;
      })()`,
    );
    if (base !== args.apiBase) {
      // 接口地址被改过，要重载让 auth.js 重新读
      await client.send('Page.reload');
      await sleep(800);
      await waitFor(
        async () => evaluate(client, "document.readyState === 'complete' && !!document.getElementById('authCard')"),
        { timeout: 20000, label: '重载后页面' },
      );
    }

    await evaluate(
      client,
      `(() => {
        document.getElementById('authUser').value = ${JSON.stringify(args.adminUser)};
        document.getElementById('authPass').value = ${JSON.stringify(args.adminPass)};
        document.getElementById('btnLogin').click();
        return true;
      })()`,
    );

    const loggedIn = await waitFor(
      async () =>
        evaluate(
          client,
          `document.getElementById('panel') && !document.getElementById('panel').classList.contains('hidden')`,
        ),
      { timeout: 20000, label: '管理员登录' },
    ).catch(async () => {
      const msg = await evaluate(client, "document.getElementById('authMsg').textContent.trim()");
      throw new Error(`登录失败：${msg || '面板没有出现'}`);
    });
    check('管理员登录后面板出现', Boolean(loggedIn));

    const header = await evaluate(
      client,
      `({ who: document.getElementById('who').textContent.trim(), role: document.getElementById('rolePill').textContent.trim() })`,
    );
    check('页头显示管理员身份', header.role === '管理员' && header.who.length > 0, `${header.who} / ${header.role}`);

    // ---- 3. 总览与统计 ----
    const stats = await waitFor(
      async () => {
        const v = await evaluate(
          client,
          `(() => {
            const num = (id) => Number((document.getElementById(id)?.textContent || '0').replace(/[^0-9.]/g, ''));
            return {
              users: num('cUsers'), gesture: num('cGesture'), image: num('cImage'), chat: num('cChat'),
              kinds: num('cKinds'), conf: document.getElementById('cConf').textContent.trim(),
              bars: document.querySelectorAll('#bars .bar').length,
              spark: document.querySelectorAll('#spark .col').length,
              updated: document.getElementById('updatedAt').textContent.trim()
            };
          })()`,
        );
        return v.users > 0 ? v : null;
      },
      { timeout: 20000, label: '总览数据' },
    );
    check('统计卡片有数据（用户 > 0）', stats.users > 0, `用户 ${stats.users} / 手势 ${stats.gesture} / 图片 ${stats.image} / 问答 ${stats.chat}`);
    check('手势分布有柱子', stats.bars > 0, `${stats.bars} 种手势`);
    check('近 7 天趋势是 7 格', stats.spark === 7, `${stats.spark} 格`);
    check('平均置信度是百分比', /%$/.test(stats.conf), stats.conf);
    check('显示刷新时间', stats.updated.length > 0, stats.updated);

    // ---- 4. 用户表 ----
    const users = await waitFor(
      async () => {
        const v = await evaluate(
          client,
          `({
            rows: document.querySelectorAll('#userWrap tbody tr').length,
            page: document.getElementById('userPage').textContent.trim(),
            hasRoleSelect: !!document.querySelector('#userWrap select[data-uid]'),
            hasCounts: document.querySelectorAll('#userWrap tbody tr').length
              ? document.querySelector('#userWrap tbody tr').children.length : 0
          })`,
        );
        return v.rows > 0 ? v : null;
      },
      { timeout: 20000, label: '用户表' },
    );
    check('用户表渲染出数据', users.rows > 0, `${users.rows} 行 / ${users.page}`);
    check('用户表有角色下拉', users.hasRoleSelect);
    check('用户表列数完整（含三类记录数）', users.hasCounts >= 9, `${users.hasCounts} 列`);

    // ---- 5. 记录 tab ----
    // 注意：点完 tab 到请求回来之间，表格里还是上一个 tab 的内容。
    // 所以不能用"行数 > 0"判断，必须等表头换成目标 tab 的列名——否则会在旧表格上误判通过。
    const switchTab = async (tab, headerWord) => {
      await evaluate(client, `document.querySelector('.tabs button[data-tab="${tab}"]').click(), true`);
      await waitFor(
        async () =>
          evaluate(
            client,
            `(() => {
              const active = document.querySelector('.tabs button[data-tab="${tab}"]').classList.contains('active');
              const head = (document.querySelector('#recWrap thead')?.textContent || '');
              const rows = document.querySelectorAll('#recWrap tbody tr').length;
              return active && head.includes(${JSON.stringify(headerWord)}) && rows > 0;
            })()`,
          ),
        { timeout: 20000, label: `${tab} 表格` },
      );
      return evaluate(client, `document.querySelectorAll('#recWrap tbody tr').length`);
    };

    const gRows = await switchTab('gesture', '动作');
    check('手势记录 tab 有数据', gRows > 0, `${gRows} 行`);

    await switchTab('image', '缩略图');
    const img = await waitFor(
      async () => {
        const v = await evaluate(
          client,
          `(() => {
            const rows = document.querySelectorAll('#recWrap tbody tr').length;
            const imgs = [...document.querySelectorAll('#recWrap img.thumb')];
            return {
              rows,
              imgs: imgs.length,
              loaded: imgs.filter((i) => i.complete && i.naturalWidth > 0).length,
              // "complete 但宽度为 0" 才是真的坏图（404 / 解码失败）；
              // 视口外未被 lazy 触发的图是 complete=false，不算失败
              failed: imgs.filter((i) => i.complete && i.naturalWidth === 0).length,
              page: document.getElementById('recPage').textContent.trim(),
            };
          })()`,
        );
        return v.rows > 0 && v.loaded > 0 && v.failed === 0 ? v : null;
      },
      { timeout: 20000, label: '图片缩略图' },
    );
    check('图片识别 tab 有数据', img.rows > 0, `${img.rows} 行`);
    check(
      '缩略图能加载且没有坏图',
      img.loaded > 0 && img.failed === 0,
      `${img.loaded}/${img.imgs} 张已加载（loading=lazy，视口外的暂不加载）`,
    );
    check('图片记录分页页脚有总数', /\d+\s*\/\s*\d+/.test(img.page), img.page);

    const cRows = await switchTab('chat', '回答');
    check('问答记录 tab 有数据', cRows > 0, `${cRows} 行`);

    // ---- 6. 页面没报错 ----
    const realErrors = client.exceptions.filter((e) => !/favicon/i.test(e));
    check('页面无未捕获异常', realErrors.length === 0, realErrors.slice(0, 2).join(' | '));

    // 可选：存一张整页截图（答辩材料 / 代码审查时用来对照）
    if (args.screenshot) {
      await evaluate(client, 'window.scrollTo(0, 0), true');
      await sleep(300);
      const shot = await client.send('Page.captureScreenshot', {
        format: 'png',
        captureBeyondViewport: true,
      });
      const { writeFileSync, mkdirSync } = await import('node:fs');
      const { dirname, resolve } = await import('node:path');
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
    if (client) {
      try {
        const shot = await client.send('Page.captureScreenshot', { format: 'png' });
        const { writeFileSync } = await import('node:fs');
        const out = join(tmpdir(), 'gwc-admin-fail.png');
        writeFileSync(out, Buffer.from(shot.data, 'base64'));
        console.log(`失败截图：${out}`);
      } catch {
        /* 截图失败不影响结论 */
      }
    }
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
      /* Windows 下句柄未释放，交给系统清理 */
    }
  }
}

process.exit(await main());

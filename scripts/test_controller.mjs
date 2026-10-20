#!/usr/bin/env node
/**
 * GestureWebController 集成测试：在 Node 里用最小 DOM 桩跑真实主循环。
 *
 * 跑法： node scripts/test_controller.mjs
 *
 * 为什么要这层测试：没有摄像头时，页面上的「抽帧 → 上传 → 防抖 → 执行动作」很容易
 * 看起来写完了、实际接线断了（事件没派发、定时器没续上、动作没调用）。这里把
 * 外部依赖（DOM / fetch / 帧源）全部替身化，只验证 SDK 自己的编排是否正确。
 */

import assert from 'node:assert/strict';

import { GestureWebController } from '../sdk/src/index.js';

// ---------------- 最小 DOM 桩 ----------------
const calls = { drawImage: 0, fillRect: 0, dispatch: [] };

function stubCtx() {
  const ctx = {
    canvas: null,
    font: '',
    fillStyle: '',
    strokeStyle: '',
    lineWidth: 1,
    textBaseline: '',
    textAlign: '',
    clearRect() {},
    save() {},
    restore() {},
    translate() {},
    scale() {},
    fillRect() {
      calls.fillRect += 1;
    },
    strokeRect() {},
    fillText() {},
    drawImage() {
      calls.drawImage += 1;
    },
    measureText: (t) => ({ width: t.length * 7 }),
  };
  return ctx;
}

function stubCanvas() {
  const ctx = stubCtx();
  const canvas = {
    width: 640,
    height: 480,
    getContext: () => ctx,
    getBoundingClientRect: () => ({ width: 640, height: 480, top: 0, left: 0 }),
    toBlob: (cb) => cb(new Blob(['fake-jpeg'], { type: 'image/jpeg' })),
  };
  ctx.canvas = canvas;
  return canvas;
}

globalThis.window = {
  devicePixelRatio: 1,
  innerWidth: 1200,
  innerHeight: 800,
  scrollY: 0,
  scrollBy() {},
};
globalThis.document = {
  body: {},
  documentElement: {},
  activeElement: null,
  createElement: (tag) => (tag === 'canvas' ? stubCanvas() : { style: {}, appendChild() {} }),
  elementFromPoint: () => null,
  addEventListener() {},
  dispatchEvent(ev) {
    calls.dispatch.push(ev.type);
    return true;
  },
};
globalThis.requestAnimationFrame = (cb) => setTimeout(() => cb(performance.now()), 16);
globalThis.cancelAnimationFrame = (id) => clearTimeout(id);

// ---------------- 帧源替身 ----------------
function fakeSource(gestures, options = {}) {
  return {
    kind: 'fake',
    label: '替身帧源',
    ready: true,
    drawable: {},
    grabCount: 0,
    async grab() {
      this.grabCount += 1;
      return { blob: new Blob(['fake'], { type: 'image/jpeg' }), width: 640, height: 480 };
    },
    stop() {
      this.stopped = true;
    },
  };
}

// ---------------- fetch 替身 ----------------
function installFetch(
  gesturesForFrame,
  { failTimes = 0, reportStatus = 201, reportReason = '数据库不可用' } = {}
) {
  let fail = failTimes;
  const seen = { predict: 0, health: 0, report: [] };
  globalThis.fetch = async (url, options = {}) => {
    if (String(url).endsWith('/api/records/gesture')) {
      seen.report.push({
        body: JSON.parse(options.body || '{}'),
        headers: options.headers || {},
        method: options.method,
      });
      if (reportStatus >= 400) {
        return { ok: false, status: reportStatus, json: async () => ({ detail: '上报失败' }) };
      }
      // 202 表示"数据库不可用，未落库，但也不算失败"
      if (reportStatus === 202) {
        return {
          ok: true,
          status: 202,
          json: async () => ({ ok: true, saved: false, reason: reportReason }),
        };
      }
      return {
        ok: true,
        status: 201,
        json: async () => ({ ok: true, saved: true, record: { record_id: seen.report.length } }),
      };
    }
    if (String(url).endsWith('/api/health')) {
      seen.health += 1;
      return {
        ok: true,
        json: async () => ({
          model: 'YOLOv10n_gestures.pt',
          model_loaded: true,
          imgsz: 640,
          classes: 34,
          debounce: { frame: 3, confThreshold: 0.35, cooldownMs: 300 },
          gestures: [],
        }),
      };
    }
    seen.predict += 1;
    if (fail > 0) {
      fail -= 1;
      return { ok: false, status: 503, json: async () => ({ detail: '模型未就绪' }) };
    }
    return {
      ok: true,
      json: async () => ({
        ok: true,
        infer_ms: 42,
        image_size: [640, 480],
        gestures: gesturesForFrame(seen.predict),
      }),
    };
  };
  return seen;
}

const G = (id, conf = 0.9) => ({
  id,
  conf,
  class: id,
  label: id,
  action: 'scroll_down',
  action_label: '下翻页',
  box: [10, 10, 100, 120],
});

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let passed = 0;
const failures = [];

async function test(name, fn) {
  try {
    await fn();
    passed += 1;
    console.log(`  ✅ ${name}`);
  } catch (err) {
    failures.push({ name, err });
    console.log(`  ❌ ${name}\n     ${err.message}`);
  }
}

console.log('GestureWebController 集成测试（Node + DOM 桩）\n');

await test('主循环跑通：3 帧后触发一次并执行动作', async () => {
  const seen = installFetch(() => [G('victory')]);
  const fired = [];
  const actionCalls = [];
  const canvas = stubCanvas();

  const ctrl = new GestureWebController({
    canvas,
    endpoint: 'http://127.0.0.1:8000',
    fps: 20,
    debounce: { cooldownMs: 600 },
    actions: {
      scroll_down: ({ gesture }) => {
        actionCalls.push(gesture.id);
        return { ok: true, message: '测试动作已执行' };
      },
    },
  });
  ctrl.on('gestureTrigger', (p) => fired.push(p.gesture.id));

  await ctrl.start({ source: fakeSource() });
  await sleep(400);
  ctrl.stop();

  assert.equal(seen.health, 1, '启动时应拉一次 /api/health 同步防抖参数');
  assert.ok(seen.predict >= 3, `至少识别 3 帧，实际 ${seen.predict}`);
  assert.deepEqual(fired, ['victory'], '应只触发一次（冷却生效）');
  assert.deepEqual(actionCalls, ['victory'], '触发后应执行对应动作');
  assert.ok(calls.dispatch.includes('gestureweb:action'), '动作执行后应派发 DOM 事件');
  assert.ok(calls.drawImage > 0, '画布应被绘制过（预览在跑）');
});

await test('防抖参数以服务端为准（配置单一来源）', async () => {
  installFetch(() => []);
  const ctrl = new GestureWebController({ canvas: stubCanvas(), fps: 20 });
  await ctrl.start({ source: fakeSource() });
  assert.equal(ctrl.debouncer.cooldownMs, 300, '应采用 /api/health 返回的 cooldownMs');
  assert.equal(ctrl.debouncer.frame, 3);
  assert.equal(ctrl.debouncer.confThreshold, 0.35);
  ctrl.stop();
});

await test('页面显式参数优先于服务端配置', async () => {
  installFetch(() => []);
  const ctrl = new GestureWebController({ canvas: stubCanvas(), fps: 20, debounce: { frame: 5 } });
  await ctrl.start({ source: fakeSource() });
  assert.equal(ctrl.debouncer.frame, 5, '用户指定 frame=5 不应被服务端覆盖');
  assert.equal(ctrl.debouncer.cooldownMs, 300, '未指定的项仍取服务端值');
  ctrl.stop();
});

await test('识别失败不中断循环，且计入错误统计', async () => {
  installFetch(() => [G('victory')], { failTimes: 2 });
  const errors = [];
  const ctrl = new GestureWebController({ canvas: stubCanvas(), fps: 20 });
  ctrl.on('error', (e) => errors.push(e.message));

  await ctrl.start({ source: fakeSource() });
  await sleep(400);
  const stats = { ...ctrl.stats };
  ctrl.stop();

  assert.ok(errors.length >= 1, '应上报错误');
  assert.match(errors[0], /503/, '错误信息应带状态码');
  assert.ok(stats.frames >= 1, '失败后循环应继续，后续帧仍能识别');
});

await test('stop() 会停掉帧源并清空状态', async () => {
  installFetch(() => []);
  const source = fakeSource();
  const ctrl = new GestureWebController({ canvas: stubCanvas(), fps: 20 });
  await ctrl.start({ source });
  await sleep(80);
  ctrl.stop();
  assert.equal(source.stopped, true, 'stop() 必须释放帧源（摄像头要关灯）');
  assert.equal(ctrl.running, false);
  assert.equal(ctrl.source, null);
});

await test('默认动作实现：scroll_down 真的调用滚动', async () => {
  let scrolled = null;
  globalThis.window.scrollBy = (opt) => {
    scrolled = opt;
  };
  const { ActionRunner } = await import('../sdk/src/actions.js');
  const runner = new ActionRunner();
  const result = await runner.run('scroll_down', G('victory'));
  assert.equal(result.ok, true);
  assert.ok(scrolled?.top > 0, `应向下滚动，实际 ${JSON.stringify(scrolled)}`);
  assert.match(result.message, /下翻/);
});

await test('截屏未注入 capture 时如实失败，不假装成功', async () => {
  const { ActionRunner } = await import('../sdk/src/actions.js');
  const runner = new ActionRunner();
  const result = await runner.run('screenshot', G('open_palm'));
  assert.equal(result.ok, false);
  assert.match(result.message, /capture/);
});

await test('截屏注入 capture 后返回产物并回调 onScreenshot', async () => {
  const { ActionRunner } = await import('../sdk/src/actions.js');
  const shots = [];
  const fakeShot = {
    blob: { size: 2048, type: 'image/jpeg' },
    url: 'blob:fake',
    width: 1280,
    height: 720,
    cssWidth: 640,
    cssHeight: 360,
    ms: 120,
    at: Date.now(),
  };
  const runner = new ActionRunner({
    context: {
      capture: async () => fakeShot,
      onScreenshot: (shot) => shots.push(shot),
    },
  });
  const result = await runner.run('screenshot', G('open_palm'));
  assert.equal(result.ok, true, result.message);
  assert.equal(shots.length, 1, 'onScreenshot 应被调用一次');
  assert.equal(result.screenshot, fakeShot, '产物应随 action 一起返回，供页面预览');
  assert.match(result.message, /640×360/);
});

await test('🤞 选图失败时不抛错，只如实返回原因', async () => {
  const { ActionRunner } = await import('../sdk/src/actions.js');
  const runner = new ActionRunner({ context: { accept: async () => ({ ok: false, message: '未选择图片' }) } });
  const result = await runner.run('image_recognition', G('cross_fingers'));
  assert.equal(result.ok, false);
  assert.match(result.message, /未选择/);
});

await test('🤟 截屏 + 识别串成一条链', async () => {
  const { ActionRunner } = await import('../sdk/src/actions.js');
  const calls = [];
  const fakeShot = { blob: { size: 1, type: 'image/jpeg' }, url: 'blob:x', cssWidth: 1, cssHeight: 1, width: 1, height: 1, ms: 5, at: 1 };
  const runner = new ActionRunner({
    context: {
      capture: async () => fakeShot,
      onScreenshot: () => calls.push('shot'),
      recognize: async (blob, opts) => {
        calls.push(`recognize:${opts.source}`);
        return { label: '张开手掌', result: '识别到 🖐️ 张开手掌' };
      },
    },
  });
  const result = await runner.run('screenshot_ai_search', G('love_you'));
  assert.equal(result.ok, true, result.message);
  assert.deepEqual(calls, ['shot', 'recognize:screenshot']);
  assert.equal(result.recognition.label, '张开手掌');
});

await test('动作抛异常不会炸掉链路', async () => {
  const { ActionRunner } = await import('../sdk/src/actions.js');
  const runner = new ActionRunner({
    handlers: {
      confirm: () => {
        throw new Error('故意抛错');
      },
    },
  });
  const result = await runner.run('confirm', G('thumb_up'));
  assert.equal(result.ok, false);
  assert.match(result.message, /故意抛错/);
});

await test('触发后上报一次，字段与 token 正确', async () => {
  const seen = installFetch(() => [G('victory')]);
  const reports = [];
  const ctrl = new GestureWebController({
    canvas: stubCanvas(),
    fps: 20,
    debounce: { cooldownMs: 600 },
    token: () => 'token-abc',
  });
  ctrl.on('report', (p) => reports.push(p));

  await ctrl.start({ source: fakeSource() });
  await sleep(400);
  ctrl.stop();
  await sleep(30); // 上报是 fire-and-forget，等它落地

  assert.equal(seen.report.length, 1, `应只上报一次，实际 ${seen.report.length}`);
  const sent = seen.report[0];
  assert.equal(sent.method, 'POST');
  assert.equal(sent.body.gesture_type, 'victory');
  assert.equal(sent.body.source, 'unknown', '自定义帧源应报 unknown 而不是 422');
  assert.equal(sent.headers.Authorization, 'Bearer token-abc', '登录态应带 token');
  assert.equal(reports[0]?.ok, true, '应派发 report 成功事件');
  assert.equal(ctrl.stats.reports, 1);
});

await test('数据库不可用（202 未落库）不影响动作执行', async () => {
  installFetch(() => [G('victory')], { reportStatus: 202 });
  const actionCalls = [];
  const ctrl = new GestureWebController({
    canvas: stubCanvas(),
    fps: 20,
    debounce: { cooldownMs: 600 },
    actions: {
      scroll_down: () => {
        actionCalls.push(1);
        return { ok: true, message: 'ok' };
      },
    },
  });

  await ctrl.start({ source: fakeSource() });
  await sleep(400);
  ctrl.stop();

  assert.equal(actionCalls.length, 1, '上报未落库时动作必须照常执行');
  assert.equal(ctrl.stats.reports, 0, '未落库不应计入成功数');
});

await test('上报接口报错不影响动作，且计入 reportErrors', async () => {
  installFetch(() => [G('victory')], { reportStatus: 500 });
  const actionCalls = [];
  const ctrl = new GestureWebController({
    canvas: stubCanvas(),
    fps: 20,
    debounce: { cooldownMs: 600 },
    actions: {
      scroll_down: () => {
        actionCalls.push(1);
        return { ok: true, message: 'ok' };
      },
    },
  });

  await ctrl.start({ source: fakeSource() });
  await sleep(400);
  ctrl.stop();
  await sleep(30);

  assert.equal(actionCalls.length, 1);
  assert.equal(ctrl.stats.reportErrors, 1, '上报失败应被记录但不抛出');
});

await test('report:false 时完全不发上报请求', async () => {
  const seen = installFetch(() => [G('victory')]);
  const ctrl = new GestureWebController({
    canvas: stubCanvas(),
    fps: 20,
    debounce: { cooldownMs: 600 },
    report: false,
  });
  await ctrl.start({ source: fakeSource() });
  await sleep(400);
  ctrl.stop();
  assert.equal(seen.report.length, 0, '关闭上报后不应有请求');
});

console.log(`\n${failures.length ? '❌' : '✅'} 通过 ${passed}/${passed + failures.length}`);if (failures.length) {
  for (const f of failures) console.error(`\n${f.name}\n${f.err.stack}`);
  process.exit(1);
}
process.exit(0);

#!/usr/bin/env node
/**
 * 防抖逻辑单测（纯 Node，无需浏览器、无需摄像头）。
 *
 * 跑法： node scripts/test_sdk.mjs
 * 说明：防抖是整条链路里最容易出错、又最难靠肉眼发现的一环（"比了没反应 / 比一次翻两页"），
 *       所以把它抽成无 DOM 的纯函数，用固定时间序列覆盖边界情况。
 */

import assert from 'node:assert/strict';

import { GestureDebouncer } from '../sdk/src/debounce.js';

const G = (id, conf = 0.9) => ({ id, conf, action: 'noop' });

let passed = 0;
const failures = [];

function test(name, fn) {
  try {
    fn();
    passed += 1;
    console.log(`  ✅ ${name}`);
  } catch (err) {
    failures.push({ name, err });
    console.log(`  ❌ ${name}\n     ${err.message}`);
  }
}

/** 造一个时钟可控的实例：tick(ms) 手动推进时间，避免真实时钟带来的抖动 */
function make(overrides = {}) {
  let t = 1000;
  const d = new GestureDebouncer({
    frame: 3,
    cooldownMs: 800,
    confThreshold: 0.35,
    missTolerance: 1,
    ...overrides,
  });
  return { d, tick: (ms = 125) => (t += ms) };
}

console.log('防抖逻辑单测\n');

test('连续 3 帧同手势 → 第 3 帧触发一次', () => {
  const { d, tick } = make();
  assert.equal(d.push([G('victory')], tick()), null, '第 1 帧不该触发');
  assert.equal(d.push([G('victory')], tick()), null, '第 2 帧不该触发');
  const fired = d.push([G('victory')], tick());
  assert.ok(fired, '第 3 帧应触发');
  assert.equal(fired.id, 'victory');
  assert.equal(fired.streak, 3);
});

test('交替手势永不触发（防止误当成同一个手势）', () => {
  const { d, tick } = make();
  for (const id of ['victory', 'point_up', 'victory', 'point_up', 'victory', 'point_up']) {
    assert.equal(d.push([G(id)], tick()), null);
  }
  assert.equal(d.streak, 1, '换手势后必须重新计数');
});

test('冷却期内不触发，冷却过后需重新攒满 3 帧', () => {
  const { d, tick } = make();
  for (let i = 0; i < 3; i += 1) d.push([G('open_palm')], tick(300)); // t=1000→1900，第 3 帧触发
  // 连喂 3 帧，全部落在 800ms 冷却窗口内
  for (let i = 0; i < 3; i += 1) {
    assert.equal(d.push([G('open_palm')], tick(200)), null, '冷却期内不该触发');
  }
  assert.equal(d.streak, 0, '冷却被撞到时要清零，否则冷却一结束就会立刻连发');
  // 冷却已过（累计推进远超 800ms），重新攒 3 帧应再次触发
  for (let i = 0; i < 2; i += 1) d.push([G('open_palm')], tick(200));
  assert.ok(d.push([G('open_palm')], tick(200)), '冷却结束后攒满应再次触发');
});

test('冷却按手势各自计算：A 冷却中不影响 B', () => {
  const { d, tick } = make();
  for (let i = 0; i < 3; i += 1) d.push([G('open_palm')], tick());
  d.push([G('thumb_up')], tick());
  d.push([G('thumb_up')], tick());
  assert.ok(d.push([G('thumb_up')], tick()), '另一个手势应能正常触发');
});

test('掉 1 帧不打断计数，连丢 2 帧归零', () => {
  const tolerant = make();
  tolerant.d.push([G('love_you')], tolerant.tick());
  tolerant.d.push([], tolerant.tick()); // 丢 1 帧，计数保留
  tolerant.d.push([G('love_you')], tolerant.tick());
  assert.ok(tolerant.d.push([G('love_you')], tolerant.tick()), '容忍 1 帧丢失时应凑满 3 帧');

  const strict = make();
  strict.d.push([G('love_you')], strict.tick());
  strict.d.push([], strict.tick());
  strict.d.push([], strict.tick());
  assert.equal(strict.d.push([G('love_you')], strict.tick()), null, '连丢 2 帧后计数归零');
  assert.equal(strict.d.streak, 1);
});

test('低于兜底阈值的候选视为没有', () => {
  const { d, tick } = make({ confThreshold: 0.35 });
  assert.equal(d.push([G('thumb_up', 0.34)], tick()), null);
  assert.equal(d.streak, 0);
});

test('🤟 的 0.51 必须能触发（回归：SDK 不得二次卡 0.7）', () => {
  const { d, tick } = make();
  d.push([G('love_you', 0.51)], tick());
  d.push([G('love_you', 0.51)], tick());
  const fired = d.push([G('love_you', 0.51)], tick());
  assert.ok(fired, '后端已按类门槛放行 0.51，前端再卡 0.7 就等于白做');
  assert.equal(fired.id, 'love_you');
});

test('同帧多个手势取置信度最高的', () => {
  const { d, tick } = make();
  const frames = [
    [G('victory', 0.6), G('open_palm', 0.9)],
    [G('victory', 0.62), G('open_palm', 0.88)],
    [G('victory', 0.64), G('open_palm', 0.91)],
  ];
  let fired = null;
  for (const f of frames) fired = d.push(f, tick()) || fired;
  assert.equal(fired?.id, 'open_palm');
});

test('触发后计数归零，紧接着的下一帧只算第 1 帧', () => {
  const { d, tick } = make({ cooldownMs: 0 });
  for (let i = 0; i < 3; i += 1) d.push([G('victory')], tick());
  assert.equal(d.push([G('victory')], tick()), null, '第 4 帧不该再触发');
  assert.equal(d.streak, 1);
});

console.log(`\n${failures.length ? '❌' : '✅'} 通过 ${passed}/${passed + failures.length}`);
if (failures.length) {
  for (const f of failures) console.error(`\n${f.name}\n${f.err.stack}`);
  process.exit(1);
}

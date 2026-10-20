/**
 * 手势防抖：把「逐帧的识别结果」变成「一次可靠的触发」。
 *
 * 纯逻辑模块：不碰 DOM、不碰网络、时间由调用方传入，因此可以直接在 Node 里跑单测。
 * 规则（与 config/gesture_map.json 的 debounce 段一致）：
 *   1. 连续 frame 帧识别为同一手势才触发（默认 3 帧）
 *   2. 同一手势触发后进入 cooldownMs 冷却，冷却期内不累积、不触发
 *   3. 中间允许丢 missTolerance 帧（摄像头偶尔掉帧不应让计数归零）
 */

export const DEBOUNCE_DEFAULTS = {
  frame: 3,
  confThreshold: 0.35,
  cooldownMs: 800,
  missTolerance: 1,
};

export class GestureDebouncer {
  /**
   * @param {object} [options]
   * @param {number} [options.frame=3] 连续同手势帧数
   * @param {number} [options.confThreshold=0.35] 兜底置信度（应低于后端每类门槛，不得高于）
   * @param {number} [options.cooldownMs=800] 同一手势触发后的冷却时间
   * @param {number} [options.missTolerance=1] 允许连续丢帧数
   */
  constructor(options = {}) {
    const cfg = { ...DEBOUNCE_DEFAULTS, ...options };
    this.frame = Math.max(1, Number(cfg.frame) || 3);
    this.confThreshold = Number(cfg.confThreshold) || 0;
    this.cooldownMs = Math.max(0, Number(cfg.cooldownMs) || 0);
    this.missTolerance = Math.max(0, Number(cfg.missTolerance) || 0);
    this.reset();
  }

  reset() {
    /** 当前累计的手势 id（null 表示未在累计） */
    this.id = null;
    /** 当前累计帧数 */
    this.streak = 0;
    /** 连续丢帧数 */
    this.misses = 0;
    /** 每个手势上次触发时间 */
    this.lastFireAt = new Map();
  }

  /** 供调试与页面展示的只读快照 */
  get state() {
    return { id: this.id, streak: this.streak, misses: this.misses, frame: this.frame };
  }

  /**
   * 喂一帧识别结果。
   * @param {Array<{id:string, conf:number}>} gestures 后端返回的手势列表（可能为空）
   * @param {number} [now] 当前时间戳（毫秒），默认 Date.now()
   * @returns {{id:string, gesture:object, streak:number, at:number}|null} 触发时返回该手势，否则 null
   */
  push(gestures, now = Date.now()) {
    const top = pickTop(gestures, this.confThreshold);

    if (!top) {
      // 没识别到：允许短暂掉帧，超过容忍度才清零
      this.misses += 1;
      if (this.misses > this.missTolerance) {
        this.id = null;
        this.streak = 0;
      }
      return null;
    }

    this.misses = 0;
    if (top.id === this.id) {
      this.streak += 1;
    } else {
      this.id = top.id;
      this.streak = 1;
    }

    if (this.streak < this.frame) return null;

    // 冷却期内不累积：清空计数，冷却结束后必须重新攒满 frame 帧，
    // 避免「手一直比着 → 冷却一结束就立刻再触发」
    const last = this.lastFireAt.get(top.id) ?? -Infinity;
    if (now - last < this.cooldownMs) {
      this.streak = 0;
      return null;
    }

    this.lastFireAt.set(top.id, now);
    this.streak = 0;
    return { id: top.id, gesture: top, streak: this.frame, at: now };
  }
}

/** 取置信度最高的一个手势；低于兜底阈值视为没有 */
function pickTop(gestures, minConf) {
  if (!Array.isArray(gestures) || gestures.length === 0) return null;
  let top = null;
  for (const g of gestures) {
    if (!g || typeof g.id !== 'string') continue;
    const conf = Number(g.conf) || 0;
    if (conf < minConf) continue;
    if (!top || conf > Number(top.conf)) top = g;
  }
  return top;
}

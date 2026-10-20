/**
 * GestureWebController：对外唯一入口。
 *
 * 用法：
 *   const ctrl = new GestureWebController({ canvas, endpoint: 'http://127.0.0.1:8000' });
 *   await ctrl.start();                        // 默认开摄像头
 *   await ctrl.start({ source: myImageSource }); // 或者换任意帧来源（无摄像头时）
 *   ctrl.on('gestureTrigger', ({ gesture }) => console.log(gesture.id));
 *
 * 一条时间线：抽帧（出帧率 fps）→ 上传识别 → 防抖 → 执行动作；
 * 预览单独走 requestAnimationFrame，保证画面 60fps 不跟着识别卡顿。
 */

import { ActionRunner } from './actions.js';
import { FrameSource } from './capture.js';
import { GestureDebouncer } from './debounce.js';
import { Overlay } from './overlay.js';
import { ScreenshotStore, captureViewport, downloadShot } from './screenshot.js';

export { FrameSource } from './capture.js';
export { GestureDebouncer } from './debounce.js';
export { Overlay } from './overlay.js';
export { ActionRunner, ACTIONS } from './actions.js';
export { ScreenshotStore, captureViewport, downloadShot, loadHtml2Canvas } from './screenshot.js';

const DEFAULTS = {
  endpoint: 'http://127.0.0.1:8000',
  fps: 8,
  executeActions: true,
  mirror: true,
  debounce: {},
  report: true,
  token: null,
  enableImageRec: true,
  enableScreenshotSearch: true,
  screenshotLimit: 5,
  screenshot: {},
};

export class GestureWebController {
  /**
   * @param {object} options
   * @param {HTMLCanvasElement} options.canvas 预览画布（框会画在上面）
   * @param {string} [options.endpoint] 后端地址
   * @param {number} [options.fps=8] 抽帧频率
   * @param {number} [options.conf] 覆盖后端默认门槛（调试用，一般不要传）
   * @param {number} [options.imgsz] 覆盖推理分辨率
   * @param {boolean} [options.executeActions=true] 是否自动执行动作
   * @param {boolean} [options.mirror=true] 预览镜像
   * @param {object} [options.debounce] 覆盖防抖参数（frame/confThreshold/cooldownMs）
   * @param {object} [options.actions] 覆盖动作实现
   * @param {Window|HTMLElement} [options.container=window] 滚动与点击的作用域
   * @param {boolean} [options.report=true] 是否把触发事件上报到后端记录表
   * @param {string|Function} [options.token] 登录 token，或返回 token 的函数
   * @param {boolean} [options.enableImageRec=true] 是否启用 🤞 手势触发图片识别
   * @param {boolean} [options.enableScreenshotSearch=true] 是否启用 🤟 截屏 + AI 搜索
   * @param {number} [options.screenshotLimit=5] 内存里保留最近几张截图
   * @param {object} [options.screenshot] 截屏参数（scale / type / quality / includePreview）
   * @param {Function} [options.pickImage] 由页面提供的选图函数，🤞 手势会调用它
   */
  constructor(options = {}) {
    const cfg = { ...DEFAULTS, ...options };
    if (!cfg.canvas) throw new Error('缺少 canvas：预览需要一张画布');

    this.endpoint = String(cfg.endpoint).replace(/\/+$/, '');
    this.fps = Math.min(30, Math.max(1, Number(cfg.fps) || 8));
    this.executeActions = cfg.executeActions !== false;
    this.conf = cfg.conf;
    this.imgsz = cfg.imgsz;
    this.canvas = cfg.canvas;
    this.report = cfg.report !== false;
    this._tokenSource = cfg.token ?? null;
    this._guestId = `guest_${Math.random().toString(36).slice(2, 10)}`;

    this.overlay = new Overlay(cfg.canvas, { mirror: cfg.mirror });
    this._debounceOverride = { ...(cfg.debounce || {}) };
    this.debouncer = new GestureDebouncer(this._debounceOverride);

    // 截图：预览要排除摄像头画布（否则截出来的网页中间嵌一个小窗），
    // 用 data 属性标记而不是写死 id，业务页换 canvas 也不用改 SDK
    this.screenshotOptions = { ...(cfg.screenshot || {}) };
    if (this.screenshotOptions.includePreview !== true && this.canvas?.dataset) {
      this.canvas.dataset.gwcIgnore = 'true';
    }
    this.screenshots = new ScreenshotStore({ limit: cfg.screenshotLimit });
    this._pickImage = typeof cfg.pickImage === 'function' ? cfg.pickImage : null;

    const context = {
      capture: (opts) => this.captureScreenshot({ ...opts, register: false }),
      screenshotOptions: this.screenshotOptions,
      onScreenshot: (shot) => this._registerShot(shot),
      recognize: (image, opts) => this.recognizeImage(image, opts),
      accept: () => this.requestImagePick(),
    };
    if (cfg.enableImageRec === false) {
      context.accept = null;
    }
    if (cfg.enableScreenshotSearch === false) {
      context.recognize = null;
    }

    this.actions = new ActionRunner({
      container: cfg.container || window,
      handlers: cfg.actions,
      context,
      onAction: (payload) => this._emit('action', payload),
    });

    this.source = null;
    this.running = false;
    this.frameSize = { width: 640, height: 480 };
    this.lastGestures = [];
    this.stats = {
      frames: 0,
      hits: 0, // 有识别结果的帧数
      triggers: 0,
      errors: 0,
      reports: 0, // 上报成功的触发次数
      reportErrors: 0,
      screenshots: 0,
      recognitions: 0,
      lastInferMs: 0,
      avgInferMs: 0,
      startedAt: 0,
    };

    this._handlers = new Map();
    this._raf = 0;
    this._timer = 0;
    this._busy = false;
  }

  // ---------- 事件 ----------

  on(event, cb) {
    if (!this._handlers.has(event)) this._handlers.set(event, new Set());
    this._handlers.get(event).add(cb);
    return () => this.off(event, cb);
  }

  off(event, cb) {
    this._handlers.get(event)?.delete(cb);
  }

  _emit(event, payload) {
    const set = this._handlers.get(event);
    if (!set) return;
    for (const cb of set) {
      try {
        cb(payload);
      } catch (err) {
        console.error(`[GestureWebController] ${event} 回调异常`, err);
      }
    }
  }

  // ---------- 生命周期 ----------

  /**
   * 启动。
   * @param {object} [opts]
   * @param {FrameSource} [opts.source] 指定帧来源；不传则开摄像头
   */
  async start(opts = {}) {
    if (this.running) return this;
    this.source = opts.source || (await FrameSource.camera());
    this.running = true;
    this.stats.startedAt = Date.now();

    await this._syncServerConfig();
    this.debouncer.reset();
    this.overlay.idle('正在识别…');

    this._loopPreview();
    this._emit('started', { source: this.source.kind, label: this.source.label, fps: this.fps });
    this._scheduleNext(0);
    return this;
  }

  stop() {
    this.running = false;
    clearTimeout(this._timer);
    cancelAnimationFrame(this._raf);
    this._raf = 0;
    this.source?.stop?.();
    this.source = null;
    this.lastGestures = [];
    this.debouncer.reset();
    this.overlay.idle('已停止');
    this._emit('stopped', { stats: { ...this.stats } });
  }

  /** 运行中切换帧来源（例如摄像头 → 图片序列），不重置统计 */  async switchSource(source) {
    const wasRunning = this.running;
    if (wasRunning) {
      this.running = false;
      clearTimeout(this._timer);
      cancelAnimationFrame(this._raf);
      this.source?.stop?.();
    }
    this.source = source;
    this.debouncer.reset();
    if (wasRunning) {
      this.running = true;
      this._loopPreview();
      this._scheduleNext(0);
    }
  }

  // ---------- 内部循环 ----------

  /** 预览独立 60fps：只重画，不发请求 */
  _loopPreview() {
    const draw = () => {
      if (!this.running || !this.source) return;
      if (this.source.ready) {
        this.overlay.render(this.source, this.lastGestures, this.frameSize);
      }
      this._raf = requestAnimationFrame(draw);
    };
    this._raf = requestAnimationFrame(draw);
  }

  _scheduleNext(delay = this._interval()) {
    clearTimeout(this._timer);
    this._timer = setTimeout(() => this._tick(), Math.max(0, delay));
  }

  _interval() {
    return Math.round(1000 / this.fps);
  }

  async _tick() {
    if (!this.running || !this.source || this._busy) return;
    this._busy = true;
    const started = performance.now();
    try {
      const frame = await this.source.grab();
      this.frameSize = { width: frame.width, height: frame.height };
      const data = await this._predict(frame.blob);

      this.stats.frames += 1;
      this.stats.lastInferMs = data.infer_ms ?? 0;
      this.stats.avgInferMs =
        (this.stats.avgInferMs * (this.stats.frames - 1) + this.stats.lastInferMs) /
        this.stats.frames;

      const gestures = Array.isArray(data.gestures) ? data.gestures : [];
      this.lastGestures = gestures;
      if (gestures.length) this.stats.hits += 1;

      const fired = this.debouncer.push(gestures);
      this._emit('frame', {
        gestures,
        inferMs: this.stats.lastInferMs,
        streak: this.debouncer.state,
        triggered: Boolean(fired),
      });

      if (fired) {
        this.stats.triggers += 1;
        this._emit('gestureTrigger', { gesture: fired.gesture, streak: fired.streak, at: fired.at });
        // 上报与动作并行：记录是附加能力，绝不能因为它慢而拖住翻页
        this._reportGesture(fired.gesture);
        if (this.executeActions) {
          // 故意不 await：截屏要 0.3~0.8s，🤞 选图可能等几十秒，
          // await 会把 8fps 的识别循环整个卡死（摄像头画面还在动，但不再识别）。
          this.actions.run(fired.gesture.action, fired.gesture).catch((err) => {
            this._emit('error', { error: err, message: err?.message || String(err) });
          });
        }
      }
    } catch (err) {
      this.stats.errors += 1;
      this._emit('error', { error: err, message: err?.message || String(err) });
    } finally {
      this._busy = false;
      if (this.running) {
        const elapsed = performance.now() - started;
        this._scheduleNext(this._interval() - elapsed);
      }
    }
  }

  // ---------- 截屏与图片识别（M3） ----------

  /**
   * 截一张当前可视区。
   * @param {object} [options] 同 captureViewport，另加 register:false 表示只返回不记录
   * @returns {Promise<object>} 截图对象（含 blob / url / width / height / ms）
   */
  async captureScreenshot(options = {}) {
    const { register = true, ...rest } = options;
    const shot = await captureViewport({ ...this.screenshotOptions, ...rest });
    return register ? this._registerShot(shot) : shot;
  }

  /** 存进内存最近截图列表并广播 screenshot 事件 */
  _registerShot(shot) {
    if (!shot) return null;
    const item = this.screenshots.add(shot);
    this.stats.screenshots += 1;
    this._emit('screenshot', { shot: item, count: this.screenshots.items.length });
    return item;
  }

  /** 下载截图；不传则下载最近一张。 */
  downloadScreenshot(shot = null) {
    return downloadShot(shot || this.screenshots.latest);
  }

  /**
   * 图片识别：把一张图交给后端 `/api/image/recognize`，结果自动落库。
   * 🤞（手势触发）和 🤟（截屏后搜索）都走这一个方法。
   *
   * @param {Blob|File|{blob:Blob}} image
   * @param {object} [opts]
   * @param {'upload'|'gesture'|'screenshot'} [opts.source='upload']
   * @returns {Promise<object>} 后端响应 {result, label, gestures, img_url, record, ...}
   */
  async recognizeImage(image, opts = {}) {
    const { source = 'upload', conf = this.conf, imgsz = this.imgsz } = opts;
    const blob = image instanceof Blob ? image : image?.blob;
    if (!(blob instanceof Blob)) throw new Error('recognizeImage 需要 Blob / File');

    const ext = blob.type === 'image/png' ? 'png' : blob.type === 'image/webp' ? 'webp' : 'jpg';
    const form = new FormData();
    form.append('image', blob, `${source}.${ext}`);
    form.append('source', source);
    if (conf != null) form.append('conf', String(conf));
    if (imgsz != null) form.append('imgsz', String(imgsz));

    const headers = {};
    const token = this._currentToken();
    if (token) headers.Authorization = `Bearer ${token}`;

    const res = await fetch(`${this.endpoint}/api/image/recognize`, {
      method: 'POST',
      body: form,
      headers,
    });
    if (!res.ok) {
      let detail = '';
      try {
        detail = (await res.json())?.detail ?? '';
      } catch {
        /* 非 JSON 错误体，忽略 */
      }
      throw new Error(`识别接口返回 ${res.status}${detail ? `：${detail}` : ''}`);
    }
    const data = await res.json();
    this.stats.recognitions += 1;
    this._emit('recognition', { source, ...data });
    return data;
  }

  /**
   * 🤞 触发的选图：具体怎么选由页面决定（options.pickImage），
   * SDK 只负责"选完就识别"。没提供时给出明确提示，不假装成功。
   * @returns {Promise<{ok:boolean, message:string, file?:File, result?:object}>}
   */
  async requestImagePick() {
    if (typeof this._pickImage !== 'function') {
      return {
        ok: false,
        message: '未配置 pickImage：请在初始化时传入 pickImage()，由页面决定用文件选择还是预设图',
      };
    }
    try {
      const file = await this._pickImage();
      if (!file) return { ok: false, message: '未选择图片' };
      const result = await this.recognizeImage(file, { source: 'gesture' });
      return { ok: true, message: `识别完成：${result.label || '—'}`, file, result };
    } catch (err) {
      return { ok: false, message: `图片识别失败：${err?.message || err}` };
    }
  }

  // ---------- 记录上报 ----------

  /** 登录后设置 token；传 null 表示退出登录（记录将以游客身份入库，uid 为 null） */
  setToken(token) {
    this._tokenSource = token || null;
  }

  _currentToken() {
    if (typeof this._tokenSource === 'function') {
      try {
        return this._tokenSource();
      } catch {
        return null;
      }
    }
    return this._tokenSource;
  }

  /**
   * 上报一次触发。刻意不 await、不抛错：
   * 后端数据库挂掉时接口会返回 202 或直接失败，都不应影响页面上的手势动作。
   */
  _reportGesture(gesture) {
    if (!this.report || !gesture) return;
    // 后端 source 只接受固定几种取值；自定义帧源统一报 unknown，避免 422 把记录全吞掉
    const allowed = ['camera', 'video', 'images'];
    const kind = this.source?.kind;
    const body = {
      gesture_type: gesture.id,
      confidence: Number(gesture.conf) || 0,
      action: gesture.action || '',
      source: allowed.includes(kind) ? kind : 'unknown',
      infer_ms: Number(this.stats.lastInferMs) || 0,
    };
    const headers = { 'Content-Type': 'application/json' };
    const token = this._currentToken();
    if (token) headers.Authorization = `Bearer ${token}`;

    fetch(`${this.endpoint}/api/records/gesture`, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      keepalive: true, // 页面切走时也能发完
    })
      .then(async (res) => {
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data?.detail || `上报返回 ${res.status}`);
        if (data.saved) this.stats.reports += 1;
        this._emit('report', { ok: Boolean(data.saved), gesture: gesture.id, data });
      })
      .catch((err) => {
        this.stats.reportErrors += 1;
        this._emit('report', { ok: false, gesture: gesture.id, error: err?.message || String(err) });
      });
  }

  async _predict(blob) {
    const form = new FormData();
    form.append('frame', blob, 'frame.jpg');
    if (this.conf != null) form.append('conf', String(this.conf));
    if (this.imgsz != null) form.append('imgsz', String(this.imgsz));

    const res = await fetch(`${this.endpoint}/api/predict`, { method: 'POST', body: form });
    if (!res.ok) {
      let detail = '';
      try {
        detail = (await res.json())?.detail ?? '';
      } catch {
        /* 忽略非 JSON 错误体 */
      }
      throw new Error(`识别接口返回 ${res.status}${detail ? `：${detail}` : ''}`);
    }
    return res.json();
  }

  /** 从后端取防抖参数（配置只有一处来源，前端不硬编码） */
  async _syncServerConfig() {
    try {
      const res = await fetch(`${this.endpoint}/api/health`);
      if (!res.ok) return;
      const health = await res.json();
      const d = health.debounce || {};
      // 页面显式指定的参数优先，不被服务端覆盖
      const merged = {
        frame: this._debounceOverride.frame ?? d.frame ?? this.debouncer.frame,
        confThreshold:
          this._debounceOverride.confThreshold ?? d.confThreshold ?? this.debouncer.confThreshold,
        cooldownMs: this._debounceOverride.cooldownMs ?? d.cooldownMs ?? this.debouncer.cooldownMs,
      };
      this.debouncer.frame = merged.frame;
      this.debouncer.confThreshold = merged.confThreshold;
      this.debouncer.cooldownMs = merged.cooldownMs;
      this._emit('config', { health, debounce: merged });
    } catch {
      /* 后端没起时不去打扰用户，识别请求会给出更明确的错误 */
    }
  }
}

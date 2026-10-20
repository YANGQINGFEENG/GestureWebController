/**
 * 动作执行：手势 id → 对页面做一件具体的事。
 *
 * 设计要点：
 * - 只做「最小可用的默认实现」，业务页可以整条替换（options.handlers）；
 * - 每个动作返回 {ok, message, ...data}，SDK 统一打到日志区，方便排查"到底执行了没"；
 * - 依赖外部能力（截屏、图片识别）的动作通过 `context` 注入，不在这里 import，
 *   这样 Node 里单测 ActionRunner 时不需要 DOM / 网络。
 */

export const ACTIONS = {
  scroll_down: '下翻页',
  scroll_up: '上翻页',
  screenshot: '截屏',
  confirm: '确定',
  image_recognition: '触发图片识别',
  screenshot_ai_search: '截屏 + AI 搜索',
};

/** 页面可视高度的 0.85 倍——留一点重叠，读起来不会跳字 */
const SCROLL_RATIO = 0.85;

export const defaultHandlers = {
  scroll_down({ container }) {
    return scrollBy(container, 1);
  },

  scroll_up({ container }) {
    return scrollBy(container, -1);
  },

  confirm({ container }) {
    const active = document.activeElement;
    const isReal = active && active !== document.body && active !== document.documentElement;
    if (isReal && typeof active.click === 'function') {
      active.click();
      return { ok: true, message: `已点击焦点元素 <${active.tagName.toLowerCase()}>` };
    }
    // 没有焦点元素时，点击视口中央的元素——符合"看着哪点哪"的直觉
    const rect = (container === window ? document.documentElement : container).getBoundingClientRect
      ? (container === window ? { top: 0, left: 0 } : container.getBoundingClientRect())
      : { top: 0, left: 0 };
    const cx = window.innerWidth / 2;
    const cy = window.innerHeight / 2;
    const el = document.elementFromPoint(cx - rect.left, cy - rect.top);
    if (el) {
      el.click();
      return { ok: true, message: `已点击视口中央元素 <${el.tagName.toLowerCase()}>` };
    }
    return { ok: false, message: '没有可点击的元素' };
  },

  /**
   * 🖐️ 截屏。真正的抓图由 `context.capture` 提供（sdk/src/screenshot.js 的 captureViewport），
   * 这里只负责"调用 + 汇报"，产物随 {screenshot} 一起返回给页面预览。
   */
  async screenshot({ capture, screenshotOptions, onScreenshot }) {
    if (typeof capture !== 'function') {
      return { ok: false, message: '截屏不可用：当前环境没有注入 capture（需要浏览器）' };
    }
    const shot = await capture(screenshotOptions);
    onScreenshot?.(shot);
    return {
      ok: true,
      message: `已截屏 ${shot.cssWidth}×${shot.cssHeight}（${shot.width}×${shot.height}px，${shot.ms}ms）`,
      screenshot: shot,
    };
  },

  async image_recognition({ accept }) {
    if (typeof accept !== 'function') {
      return { ok: false, message: '图片识别不可用：能力已关闭，或当前环境没有注入 accept' };
    }
    // accept() 负责"唤起选图 → 上传识别"，SDK 主循环不等它（用户可能几十秒才选完）
    const picked = await accept();
    if (!picked?.ok) {
      return { ok: false, message: picked?.message || '未完成图片识别' };
    }
    return {
      ok: true,
      message: picked.result
        ? `识别完成：${picked.result.label}｜${picked.result.result}`
        : '识别完成',
      recognition: picked.result,
    };
  },

  screenshot_ai_search({ capture, screenshotOptions, onScreenshot, recognize, source = 'screenshot' }) {
    if (typeof capture !== 'function' || typeof recognize !== 'function') {
      return { ok: false, message: '截屏 + AI 搜索不可用：缺少 capture / recognize' };
    }
    // 截屏与识别串成一条链，事件里带上 shot，页面可以先预览再等结果（M3-4）
    return (async () => {
      const shot = await capture(screenshotOptions);
      onScreenshot?.(shot);
      const result = await recognize(shot.blob, { source, shot });
      return {
        ok: true,
        message: `已截屏并识别：${result.label}`,
        screenshot: shot,
        recognition: result,
      };
    })();
  },
};

function scrollBy(container, direction) {
  const isWindow = container === window || container === document;
  const amount = Math.round((isWindow ? window.innerHeight : container.clientHeight) * SCROLL_RATIO);
  const before = isWindow ? window.scrollY : container.scrollTop;
  const target = isWindow ? window : container;
  target.scrollBy({ top: amount * direction, behavior: 'smooth' });

  const where = isWindow ? '页面' : '滚动容器';
  return {
    ok: true,
    message: `${where}${direction > 0 ? '下翻' : '上翻'} ${amount}px（当前 ${Math.round(before)}px）`,
  };
}

export class ActionRunner {
  /**
   * @param {object} [options]
   * @param {Window|HTMLElement} [options.container=window] 滚动/点击的作用域
   * @param {Object<string, Function>} [options.handlers] 覆盖默认实现
   * @param {object} [options.context] 注入给 handler 的外部能力（capture / recognize / accept …）
   * @param {(payload:object)=>void} [options.onAction] 动作结果回调
   */
  constructor(options = {}) {
    this.container = options.container || window;
    this.handlers = { ...defaultHandlers, ...(options.handlers || {}) };
    this.context = options.context || {};
    this.onAction = options.onAction || (() => {});
  }

  /** 注册/覆盖单个动作 */
  register(action, handler) {
    this.handlers[action] = handler;
  }

  /** 补齐/替换注入的能力（SDK 启动后再接上 recognize 之类） */
  setContext(context = {}) {
    this.context = { ...this.context, ...context };
  }

  /**
   * 执行动作。任何异常都吞掉并转成 {ok:false}，不让一个动作失败打断识别循环。
   * @returns {Promise<{action:string, ok:boolean, message:string}>}
   */
  async run(action, gesture) {
    const handler = this.handlers[action];
    let result;
    if (!handler) {
      result = { ok: false, message: `未注册的动作：${action}` };
    } else {
      try {
        // 固定字段放后面，避免注入的 context 覆盖 action / gesture / container
        result = (await handler({
          ...this.context,
          action,
          gesture,
          container: this.container,
        })) || {
          ok: true,
          message: '',
        };
      } catch (err) {
        result = { ok: false, message: `执行异常：${err?.message || err}` };
      }
    }
    const payload = { action, label: ACTIONS[action] || action, gesture, ...result };
    this.onAction(payload);
    // 同时派发 DOM 事件，业务页不引 SDK 内部对象也能监听
    document.dispatchEvent(new CustomEvent('gestureweb:action', { detail: payload }));
    return payload;
  }
}

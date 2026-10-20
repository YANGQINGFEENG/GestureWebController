/**
 * 动作执行：手势 id → 对页面做一件具体的事。
 *
 * 设计要点：
 * - 只做「最小可用的默认实现」，业务页可以整条替换（options.handlers）；
 * - 每个动作返回 {ok, message}，SDK 统一打到日志区，方便排查"到底执行了没"；
 * - 截屏/图片识别依赖后续里程碑的能力，这里给明确的未实现提示，不假装成功。
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

  screenshot() {
    return { ok: false, message: '截屏依赖 html2canvas，排在 M3，暂未实现' };
  },

  image_recognition() {
    return { ok: false, message: '图片识别链路排在 M3，暂未实现' };
  },

  screenshot_ai_search() {
    return { ok: false, message: '截屏 + AI 搜索链路排在 M3，暂未实现' };
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
   * @param {(payload:object)=>void} [options.onAction] 动作结果回调
   */
  constructor(options = {}) {
    this.container = options.container || window;
    this.handlers = { ...defaultHandlers, ...(options.handlers || {}) };
    this.onAction = options.onAction || (() => {});
  }

  /** 注册/覆盖单个动作（演示页用它接管截屏做占位） */
  register(action, handler) {
    this.handlers[action] = handler;
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
        result = (await handler({ action, gesture, container: this.container })) || {
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

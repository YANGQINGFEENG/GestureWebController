/**
 * 截屏：把当前可视区画成一张图（🖐️ 截屏、🤟 截屏+AI 搜索共用）。
 *
 * 为什么用 html2canvas 而不是 navigator.mediaDevices.getDisplayMedia：
 * - 后者要用户再点一次授权、且能截整个桌面/其他标签页，超出"网页手势工具"的边界，
 *   演示时多一步弹窗也很容易出岔子；
 * - html2canvas 只画当前 DOM，纯前端、零授权，符合"仅操控当前标签页"的既定边界（需求 3.6）。
 *
 * 三个必须处理好的坑：
 * 1. **滚动位置**：html2canvas 默认截整个元素；要截"用户看到的这一屏"，
 *    必须传 x/y = 当前滚动位置，同时把内部 scrollX/scrollY 归零，否则会offset 两次。
 * 2. **脚本来源**：默认从 SDK 自带的 vendor 目录加载，保证离线可用；
 *    嵌入方也可以传 scriptUrl 指到自己的 CDN。
 * 3. **清理**：blob 用 objectURL 预览，不用了要 revoke，否则长跑页面会漏内存。
 */

/**
 * 默认从 SDK 同级的 vendor 目录取（随 SDK 一起分发，不走公网）。
 * import.meta.url 在 ESM 里就是当前模块地址，天然不依赖部署路径。
 */
export const DEFAULT_SCRIPT_URL = new URL('../vendor/html2canvas.min.js', import.meta.url).href;

let _loading = null;

/**
 * 懒加载 html2canvas：第一次截屏才拉脚本，不拖慢首屏。
 * @param {string} [scriptUrl]
 * @returns {Promise<Function>}
 */
export function loadHtml2Canvas(scriptUrl = DEFAULT_SCRIPT_URL) {
  if (globalThis.html2canvas) return Promise.resolve(globalThis.html2canvas);
  if (_loading) return _loading;

  _loading = new Promise((resolve, reject) => {
    if (typeof document === 'undefined') {
      reject(new Error('当前环境没有 document，无法截屏'));
      return;
    }
    const el = document.createElement('script');
    el.src = scriptUrl;
    el.async = true;
    el.dataset.gwcIgnore = 'true'; // 别把加载器自己画进截图里
    el.onload = () => {
      if (globalThis.html2canvas) resolve(globalThis.html2canvas);
      else reject(new Error('截图库已加载但没有注册 html2canvas'));
    };
    el.onerror = () => {
      _loading = null; // 允许重试
      reject(
        new Error(
          `无法加载截图库：${scriptUrl}。请确认 sdk/vendor/html2canvas.min.js 存在，或通过 scriptUrl 指定地址`,
        ),
      );
    };
    document.head.appendChild(el);
  });
  return _loading;
}

/**
 * 截取当前可视区。
 *
 * @param {object} [options]
 * @param {number} [options.scale] 清晰度倍数，默认按 devicePixelRatio 但封顶 2（再高就是白烧内存）
 * @param {string} [options.background] 背景色，画布透明处会填这个色
 * @param {string} [options.type] 产物类型，默认 image/jpeg（体积小，适合上传）
 * @param {number} [options.quality] JPEG 质量 0~1
 * @param {string} [options.scriptUrl] 覆盖截图库地址
 * @param {(el:Element)=>boolean} [options.ignore] 额外要排除的元素（如摄像头预览）
 * @param {boolean} [options.skipPreview=true] 是否跳过 SDK 自己的预览画布（它画的是摄像头画面，不该进截图）
 * @returns {Promise<{blob:Blob, url:string, dataUrl:string, width:number, height:number,
 *                    cssWidth:number, cssHeight:number, type:string, ms:number, at:number}>}
 */
export async function captureViewport(options = {}) {
  if (typeof window === 'undefined' || typeof document === 'undefined') {
    throw new Error('截屏只能在浏览器里执行');
  }

  const dpr = window.devicePixelRatio || 1;
  const scale = clamp(options.scale ?? Math.min(2, Math.max(1, dpr)), 1, 3);
  const type = options.type || 'image/jpeg';
  const quality = options.quality ?? 0.85;
  const skipPreview = options.skipPreview !== false;
  const extraIgnore = options.ignore;

  const h2c = await loadHtml2Canvas(options.scriptUrl);
  const started = performance.now();

  const cssWidth = window.innerWidth;
  const cssHeight = window.innerHeight;
  const scrollX = window.scrollX || window.pageXOffset || 0;
  const scrollY = window.scrollY || window.pageYOffset || 0;

  const canvas = await h2c(document.documentElement, {
    // 只取"这一屏"：从当前滚动位置起，宽高等于视口
    x: scrollX,
    y: scrollY,
    width: cssWidth,
    height: cssHeight,
    windowWidth: cssWidth,
    windowHeight: cssHeight,
    scrollX: 0,
    scrollY: 0,
    scale,
    backgroundColor: options.background || '#ffffff',
    useCORS: true,
    allowTaint: false,
    logging: false,
    ignoreElements: (el) => isIgnored(el, skipPreview, extraIgnore),
  });

  const blob = await new Promise((resolve, reject) => {
    canvas.toBlob(
      (result) => (result ? resolve(result) : reject(new Error('截图编码失败（画布可能被跨域污染）'))),
      type,
      quality,
    );
  });

  return {
    blob,
    url: URL.createObjectURL(blob),
    dataUrl: canvas.toDataURL(type, quality),
    width: canvas.width,
    height: canvas.height,
    cssWidth,
    cssHeight,
    type,
    ms: Math.round(performance.now() - started),
    at: Date.now(),
  };
}

function isIgnored(el, skipPreview, extraIgnore) {
  if (!el || el.nodeType !== 1) return false;
  if (el.dataset?.gwcIgnore === 'true') return true;
  // 摄像头预览画布默认排除：否则截出来的"网页"里会嵌一个小窗，主体内容被挤掉
  if (skipPreview && el.tagName === 'CANVAS' && el.id === 'preview') return true;
  return typeof extraIgnore === 'function' ? Boolean(extraIgnore(el)) : false;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

/** 把截图存成文件（浏览器下载），文件名带时间戳，便于答辩时连点几次不覆盖。 */
export function downloadShot(shot, prefix = 'gesture-shot') {
  if (!shot?.blob) return false;
  const stamp = new Date(shot.at || Date.now())
    .toISOString()
    .replace(/[:.]/g, '-')
    .slice(0, 19);
  const ext = shot.type === 'image/png' ? 'png' : 'jpg';
  const a = document.createElement('a');
  a.href = shot.url || URL.createObjectURL(shot.blob);
  a.download = `${prefix}-${stamp}.${ext}`;
  a.dataset.gwcIgnore = 'true';
  document.body.appendChild(a);
  a.click();
  a.remove();
  return true;
}

/**
 * 最近几张截图的环形缓存：页面刷新就没了，不占磁盘也不进库。
 * 上限默认 5 张，超出时自动 revoke 最早的 objectURL。
 */
export class ScreenshotStore {
  constructor({ limit = 5 } = {}) {
    this.limit = Math.max(1, Number(limit) || 5);
    this.items = [];
  }

  add(shot) {
    const item = { ...shot, id: `shot_${shot.at}_${this.items.length}` };
    this.items.push(item);
    while (this.items.length > this.limit) {
      const dropped = this.items.shift();
      this._revoke(dropped);
    }
    return item;
  }

  get latest() {
    return this.items[this.items.length - 1] || null;
  }

  clear() {
    for (const item of this.items) this._revoke(item);
    this.items = [];
  }

  _revoke(shot) {
    if (shot?.url?.startsWith('blob:')) {
      try {
        URL.revokeObjectURL(shot.url);
      } catch {
        /* 已释放或环境不支持，忽略 */
      }
    }
  }
}

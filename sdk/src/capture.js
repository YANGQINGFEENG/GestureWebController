/**
 * 帧来源：「摄像头 / 本地视频 / 图片序列」三选一，对上暴露同一套 grab()。
 *
 * 为什么要有后两种模式：
 * - 开发机没有摄像头时，仍能验证整条链路（抽帧 → 识别 → 防抖 → 动作）；
 * - 图片序列可以稳定复现某个手势，比对着摄像头比划更适合排查"为什么不触发"。
 *
 * 抽帧宽度固定 640（ADR-007 实测：320px 起漏检），不与显示尺寸挂钩。
 */

const DEFAULT_WIDTH = 640;
const DEFAULT_QUALITY = 0.72;

export class FrameSource {
  constructor(kind, media, options = {}) {
    this.kind = kind; // 'camera' | 'video' | 'images'
    this.media = media; // HTMLVideoElement | HTMLImageElement[]
    this.width = options.width || DEFAULT_WIDTH;
    this.quality = options.quality || DEFAULT_QUALITY;
    this.label = options.label || kind;
    this.holdMs = options.holdMs ?? 1500; // 图片序列模式下每张停留多久
    this._canvas = document.createElement('canvas');
    this._ctx = this._canvas.getContext('2d');
    this._index = 0;
    this._lastAdvance = 0;
    this._objectUrls = media.__objectUrls || [];
  }

  // ---------- 构造 ----------

  /** 摄像头。需要在 localhost 或 https 下，否则 getUserMedia 会直接抛错。 */
  static async camera(options = {}) {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error('当前环境不支持摄像头：请用 localhost 或 https 打开页面');
    }
    const stream = await navigator.mediaDevices.getUserMedia({
      video: {
        width: { ideal: options.videoWidth || 1280 },
        height: { ideal: options.videoHeight || 720 },
        facingMode: options.facingMode || 'user',
        ...(options.deviceId ? { deviceId: { exact: options.deviceId } } : {}),
      },
      audio: false,
    });
    const video = document.createElement('video');
    video.srcObject = stream;
    video.muted = true;
    video.playsInline = true;
    await video.play();
    await waitFor(video, 'loadedmetadata');
    const source = new FrameSource('camera', video, { label: '摄像头', ...options });
    source._stream = stream;
    return source;
  }

  /** 本地视频文件（模拟一段固定画面，便于反复测试）。 */
  static async videoFile(file, options = {}) {
    const url = URL.createObjectURL(file);
    const video = document.createElement('video');
    video.src = url;
    video.muted = true;
    video.loop = true;
    video.playsInline = true;
    await video.play().catch(() => {});
    await waitFor(video, 'loadedmetadata');
    const source = new FrameSource('video', video, { label: `视频：${file.name}`, ...options });
    source._objectUrls = [url];
    return source;
  }

  /** 图片序列：按 holdMs 停留，每张停留期间可稳定攒够防抖帧数。 */
  static async images(files, options = {}) {
    const list = Array.from(files || []);
    if (!list.length) throw new Error('图片序列为空');
    const images = [];
    const urls = [];
    for (const file of list) {
      const url = URL.createObjectURL(file);
      urls.push(url);
      const img = new Image();
      img.src = url;
      await img.decode().catch(() => {});
      images.push(img);
    }
    const source = new FrameSource('images', images, {
      label: `图片序列（${images.length} 张）`,
      ...options,
    });
    source._objectUrls = urls;
    return source;
  }

  // ---------- 状态 ----------

  get ready() {
    if (this.kind === 'images') return this.media.length > 0;
    return this.media.readyState >= 2; // HAVE_CURRENT_DATA
  }

  /** 当前用于预览/抽帧的图像源 */
  get drawable() {
    return this.kind === 'images' ? this.media[this._index] : this.media;
  }

  get naturalSize() {
    const el = this.drawable;
    const w = el.videoWidth || el.naturalWidth || this.width;
    const h = el.videoHeight || el.naturalHeight || Math.round((this.width * 3) / 4);
    return { width: w, height: h };
  }

  /** 图片序列模式：到点切下一张（每次 grab 调用一次）。 */
  _maybeAdvance(now) {
    if (this.kind !== 'images' || this.holdMs <= 0) return;
    if (now - this._lastAdvance < this.holdMs) return;
    this._lastAdvance = now;
    this._index = (this._index + 1) % this.media.length;
  }

  // ---------- 抽帧 ----------

  /**
   * 抓一帧，返回可直接 fetch 上传的 JPEG。
   * @returns {Promise<{blob:Blob, width:number, height:number}>}
   */
  async grab() {
    this._maybeAdvance(performance.now());
    const { width: nw, height: nh } = this.naturalSize;
    const w = this.width;
    const h = Math.max(1, Math.round((w * nh) / nw));

    if (this._canvas.width !== w || this._canvas.height !== h) {
      this._canvas.width = w;
      this._canvas.height = h;
    }
    this._ctx.drawImage(this.drawable, 0, 0, w, h);

    const blob = await new Promise((resolve, reject) => {
      this._canvas.toBlob(
        (b) => (b ? resolve(b) : reject(new Error('toBlob 失败：画布无法导出图片'))),
        'image/jpeg',
        this.quality,
      );
    });
    return { blob, width: w, height: h };
  }

  stop() {
    if (this._stream) this._stream.getTracks().forEach((t) => t.stop());
    if (this.kind === 'video') this.media.pause?.();
    this._objectUrls.forEach((u) => URL.revokeObjectURL(u));
    this._objectUrls = [];
  }
}

function waitFor(el, event, timeoutMs = 8000) {
  if (el.readyState >= 2) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`等待 ${event} 超时`)), timeoutMs);
    el.addEventListener(
      event,
      () => {
        clearTimeout(timer);
        resolve();
      },
      { once: true },
    );
  });
}

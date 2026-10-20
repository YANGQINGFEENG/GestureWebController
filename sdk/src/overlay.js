/**
 * 画面叠加层：把「摄像头画面 + 识别框」画在同一张 Canvas 上。
 *
 * 关键设计：不叠加在 <video> 之上，而是自己把画面画进 Canvas。
 * 这样框坐标与画面天然对齐（都用同一套 cover 映射），不用去算 object-fit 的偏移。
 */

export class Overlay {
  /**
   * @param {HTMLCanvasElement} canvas
   * @param {object} [options]
   * @param {boolean} [options.mirror=true] 镜像预览（自拍视角更自然，框与文字会一起校正）
   * @param {boolean} [options.showLabel=true] 是否显示标签
   */
  constructor(canvas, options = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.mirror = options.mirror !== false;
    this.showLabel = options.showLabel !== false;
    this.dpr = Math.min(window.devicePixelRatio || 1, 2);
    this._empty = true;
  }

  /** 跟随容器尺寸变化重设像素（DPR 感知，高分屏不糊） */
  resize() {
    const rect = this.canvas.getBoundingClientRect();
    const w = Math.max(1, Math.round(rect.width * this.dpr));
    const h = Math.max(1, Math.round(rect.height * this.dpr));
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w;
      this.canvas.height = h;
    }
  }

  /**
   * 画一帧：底图 + 框。
   * @param {{drawable: CanvasImageSource}} source 帧来源
   * @param {Array<{box:number[], label:string, conf:number, emoji?:string}>} gestures
   * @param {{width:number, height:number}} frameSize 送检图像的像素尺寸（框坐标的参照系）
   */
  render(source, gestures = [], frameSize = { width: 640, height: 480 }) {
    this.resize();
    const { ctx, canvas } = this;
    const W = canvas.width;
    const H = canvas.height;

    ctx.clearRect(0, 0, W, H);

    // 1) 底图：按 cover 铺满，和 CSS object-fit: cover 的观感一致
    const fw = frameSize.width || 640;
    const fh = frameSize.height || 480;
    const scale = Math.max(W / fw, H / fh);
    const drawW = fw * scale;
    const drawH = fh * scale;
    const ox = (W - drawW) / 2;
    const oy = (H - drawH) / 2;

    ctx.save();
    if (this.mirror) {
      ctx.translate(W, 0);
      ctx.scale(-1, 1);
    }
    try {
      ctx.drawImage(source.drawable, 0, 0, drawW, drawH);
    } catch {
      /* 首帧 drawable 可能还没就绪，跳过即可 */
    }
    ctx.restore();
    this._empty = false;

    // 2) 框
    for (const g of gestures) {
      if (!g.box || g.box.length !== 4) continue;
      let [x1, y1, x2, y2] = g.box;
      let px1 = ox + x1 * scale;
      let px2 = ox + x2 * scale;
      const py1 = oy + y1 * scale;
      const py2 = oy + y2 * scale;
      if (this.mirror) {
        const a = W - px2;
        const b = W - px1;
        px1 = a;
        px2 = b;
      }

      const accent = COLORS[g.id] || COLORS.default;
      ctx.strokeStyle = accent;
      ctx.lineWidth = Math.max(2, Math.round(3 * this.dpr));
      ctx.strokeRect(px1, py1, px2 - px1, py2 - py1);

      if (!this.showLabel) continue;
      const text = `${g.emoji ? g.emoji + ' ' : ''}${g.label || g.id}  ${(g.conf * 100).toFixed(0)}%`;
      ctx.font = `${Math.round(13 * this.dpr)}px system-ui, -apple-system, "Microsoft YaHei", sans-serif`;
      const padX = 6 * this.dpr;
      const textW = ctx.measureText(text).width;
      const boxH = 20 * this.dpr;
      const labelY = Math.max(py1 - boxH - 2, 0);

      ctx.fillStyle = accent;
      ctx.fillRect(px1, labelY, textW + padX * 2, boxH);
      ctx.fillStyle = '#fff';
      ctx.textBaseline = 'middle';
      ctx.fillText(text, px1 + padX, labelY + boxH / 2);
    }
  }

  /** 没有画面时画占位提示（未开始 / 已停止 / 出错） */
  idle(message) {
    this.resize();
    const { ctx, canvas } = this;
    const W = canvas.width;
    const H = canvas.height;
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = 'rgba(17, 24, 39, 0.92)';
    ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = '#9ca3af';
    ctx.font = `${Math.round(15 * this.dpr)}px system-ui, -apple-system, "Microsoft YaHei", sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(message, W / 2, H / 2);
    ctx.textAlign = 'start';
    this._empty = true;
  }
}

/** 每种手势一个固定颜色，肉眼能一眼对上日志 */
const COLORS = {
  victory: '#22c55e',
  point_up: '#3b82f6',
  open_palm: '#f59e0b',
  thumb_up: '#ec4899',
  cross_fingers: '#8b5cf6',
  love_you: '#ef4444',
  default: '#ef4444',
};

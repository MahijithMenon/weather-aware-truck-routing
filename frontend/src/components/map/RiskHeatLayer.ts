import L from "leaflet";
import { RISK_RGB } from "@/lib/risk";

const CELL_PX = 4; // field resolution; upscaled with smoothing when drawn
const METERS_PER_MILE = 1609.344;

export interface HeatSample {
  lat: number;
  lon: number;
}

interface Projected {
  x: number;
  y: number;
  i: number; // index into the values array
}

/**
 * Canvas heatmap that interpolates sparse corridor samples into a smooth field.
 *
 * Each pixel cell takes an inverse-distance weighted mean of the samples within
 * `radius`, then is colored by the risk band that mean falls in, so colors
 * change exactly at the assessment's thresholds. Opacity fades out at the
 * corridor's edges (low total weight).
 *
 * Performance: samples are projected to screen space and bucketed only when
 * the view changes; changing the hour (`setValues`) just re-runs the field
 * pass on a quarter-resolution grid, a few ms for a typical corridor.
 */
export class RiskHeatLayer extends L.Layer {
  private canvas!: HTMLCanvasElement;
  private field = document.createElement("canvas");
  private samples: HeatSample[] = [];
  private values: (number | null)[] = [];
  private radiusMi = 20;
  private minAlpha = 0.3;
  private opacity = 0.75;
  private projected: Projected[] = [];
  private buckets = new Map<number, Projected[]>();
  private radiusPx = 0;
  private frame = 0;
  private dirtyProjection = true;

  setSamples(samples: HeatSample[], radiusMi: number): this {
    this.samples = samples;
    this.radiusMi = radiusMi;
    this.dirtyProjection = true;
    return this.schedule();
  }

  /** Values on the 0..4 risk scale, aligned with the samples; null = no data. */
  setValues(values: (number | null)[], minAlpha: number): this {
    this.values = values;
    this.minAlpha = minAlpha;
    return this.schedule();
  }

  setOpacity(opacity: number): this {
    this.opacity = opacity;
    if (this.canvas) this.canvas.style.opacity = String(opacity);
    return this;
  }

  onAdd(map: L.Map): this {
    this.canvas = L.DomUtil.create("canvas", "leaflet-zoom-hide risk-heat-layer");
    this.canvas.style.opacity = String(this.opacity);
    this.canvas.style.pointerEvents = "none";
    // Own pane below the vector overlays (400) so routes stay on top.
    const pane = map.getPane("heat") ?? map.createPane("heat");
    pane.style.zIndex = "350";
    pane.style.pointerEvents = "none";
    pane.appendChild(this.canvas);
    map.on("moveend resize", this.onViewChange, this);
    this.onViewChange();
    return this;
  }

  onRemove(map: L.Map): this {
    map.off("moveend resize", this.onViewChange, this);
    cancelAnimationFrame(this.frame);
    this.canvas.remove();
    return this;
  }

  private onViewChange() {
    this.dirtyProjection = true;
    this.schedule();
  }

  private schedule(): this {
    if (!this._map || this.frame) return this;
    this.frame = requestAnimationFrame(() => {
      this.frame = 0;
      this.draw();
    });
    return this;
  }

  private project() {
    const map = this._map;
    const size = map.getSize();
    const topLeft = map.containerPointToLayerPoint([0, 0]);
    L.DomUtil.setPosition(this.canvas, topLeft);
    this.canvas.width = size.x;
    this.canvas.height = size.y;
    this.canvas.style.width = `${size.x}px`;
    this.canvas.style.height = `${size.y}px`;

    // Radius in screen pixels at the map center's latitude and current zoom.
    const center = map.getCenter();
    const metersPerPx =
      (40075016.686 * Math.cos((center.lat * Math.PI) / 180)) / Math.pow(2, map.getZoom() + 8);
    this.radiusPx = Math.max((this.radiusMi * METERS_PER_MILE) / metersPerPx, 6);

    const r = this.radiusPx;
    this.projected = [];
    this.buckets.clear();
    this.samples.forEach((s, i) => {
      const p = map.latLngToContainerPoint([s.lat, s.lon]);
      if (p.x < -r || p.y < -r || p.x > size.x + r || p.y > size.y + r) return;
      const proj = { x: p.x, y: p.y, i };
      this.projected.push(proj);
      const key = this.bucketKey(Math.floor(p.x / r), Math.floor(p.y / r));
      const list = this.buckets.get(key);
      if (list) list.push(proj);
      else this.buckets.set(key, [proj]);
    });
    this.dirtyProjection = false;
  }

  private bucketKey(bx: number, by: number) {
    return (bx + 1000) * 4000 + (by + 1000);
  }

  private draw() {
    if (!this._map) return;
    if (this.dirtyProjection) this.project();
    const ctx = this.canvas.getContext("2d")!;
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    if (!this.projected.length || !this.values.length) return;

    const w = Math.ceil(this.canvas.width / CELL_PX);
    const h = Math.ceil(this.canvas.height / CELL_PX);
    this.field.width = w;
    this.field.height = h;
    const fctx = this.field.getContext("2d")!;
    const img = fctx.createImageData(w, h);
    const data = img.data;

    const r = this.radiusPx;
    const r2 = r * r;
    const values = this.values;
    const minAlpha = this.minAlpha;

    for (let gy = 0; gy < h; gy++) {
      const y = gy * CELL_PX + CELL_PX / 2;
      const by = Math.floor(y / r);
      for (let gx = 0; gx < w; gx++) {
        const x = gx * CELL_PX + CELL_PX / 2;
        const bx = Math.floor(x / r);
        let sumW = 0;
        let sumV = 0;
        for (let dy = -1; dy <= 1; dy++) {
          for (let dx = -1; dx <= 1; dx++) {
            const list = this.buckets.get(this.bucketKey(bx + dx, by + dy));
            if (!list) continue;
            for (let k = 0; k < list.length; k++) {
              const p = list[k];
              const v = values[p.i];
              if (v == null) continue;
              const ddx = p.x - x;
              const ddy = p.y - y;
              const d2 = ddx * ddx + ddy * ddy;
              if (d2 >= r2) continue;
              const f = 1 - d2 / r2;
              const wt = f * f;
              sumW += wt;
              sumV += wt * v;
            }
          }
        }
        if (sumW < 0.02) continue;
        const score = sumV / sumW;
        const band = Math.min(4, Math.max(0, Math.floor(score)));
        const [cr, cg, cb] = RISK_RGB[band];
        const coverage = Math.min(1, sumW * 1.4);
        const strength = minAlpha + (1 - minAlpha) * Math.min(1, score / 2.5);
        const o = (gy * w + gx) * 4;
        data[o] = cr;
        data[o + 1] = cg;
        data[o + 2] = cb;
        data[o + 3] = 255 * coverage * strength;
      }
    }

    fctx.putImageData(img, 0, 0);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(this.field, 0, 0, w * CELL_PX, h * CELL_PX);
  }
}

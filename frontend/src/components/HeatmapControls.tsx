"use client";

import { useEffect } from "react";
import { METRIC_INFO, METRIC_THRESHOLDS, RISK_COLORS, RISK_LABELS, formatTime } from "@/lib/risk";
import type { HeatMetric, Heatmap, RiskLevel } from "@/lib/types";

interface Props {
  heatmap: Heatmap | null;
  loading: boolean;
  error: string | null;
  hour: number;
  onHour: (h: number) => void;
  metric: HeatMetric;
  onMetric: (m: HeatMetric) => void;
  visible: boolean;
  onVisible: (v: boolean) => void;
  playing: boolean;
  onPlaying: (p: boolean) => void;
}

const METRICS: HeatMetric[] = ["risk", "wind", "rain", "snow"];
const PLAY_STEP_MS = 450;

export function HeatmapControls(props: Props) {
  const { heatmap, loading, error, hour, onHour, metric, onMetric, visible, onVisible, playing, onPlaying } = props;
  const maxHour = heatmap ? heatmap.hours.length - 1 : 48;

  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => onHour(hour >= maxHour ? 0 : hour + 1), PLAY_STEP_MS);
    return () => clearInterval(timer);
  }, [playing, hour, maxHour, onHour]);

  return (
    <div className="heat-controls" aria-label="Weather heatmap controls">
      <div className="heat-row">
        <label className="toggle">
          <input type="checkbox" checked={visible} onChange={(e) => onVisible(e.target.checked)} />
          Weather heatmap
        </label>
        <div className="segmented small" role="radiogroup" aria-label="Heatmap layer">
          {METRICS.map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={metric === m}
              className={metric === m ? "on" : undefined}
              onClick={() => onMetric(m)}
              disabled={!visible}
            >
              {m === "risk" ? "Risk" : METRIC_INFO[m].label}
            </button>
          ))}
        </div>
      </div>

      {loading && <div className="muted small">Loading corridor forecast…</div>}
      {error && <div className="form-error small">{error}</div>}

      {heatmap && (
        <>
          <div className="heat-row">
            <button
              type="button"
              className="icon"
              onClick={() => onPlaying(!playing)}
              aria-label={playing ? "Pause" : "Play forecast animation"}
            >
              {playing ? "❚❚" : "▶"}
            </button>
            <input
              type="range"
              min={0}
              max={maxHour}
              step={1}
              value={hour}
              onChange={(e) => {
                onPlaying(false);
                onHour(Number(e.target.value));
              }}
              aria-label="Forecast hour"
              aria-valuetext={`+${hour} hours, ${formatTime(heatmap.hours[hour])}`}
              className="slider"
            />
            <div className="heat-time">
              <strong>+{hour}h</strong>
              <span className="muted">{formatTime(heatmap.hours[hour])}</span>
            </div>
          </div>
          <Legend metric={metric} />
        </>
      )}
    </div>
  );
}

function Legend({ metric }: { metric: HeatMetric }) {
  const t = metric === "risk" ? null : METRIC_THRESHOLDS[metric];
  const unit = METRIC_INFO[metric].unit;
  return (
    <div className="legend">
      {RISK_LABELS.map((label, i) => (
        <span key={label} className="legend-item">
          <span className="swatch" style={{ background: RISK_COLORS[i as RiskLevel] }} />
          {label}
          {t && (
            <span className="muted">
              {" "}
              {i === 0 ? `<${t[0]}` : i === 4 ? `${metric === "wind" ? "≥" : ">"}${t[3]}` : `${t[i - 1]}–${t[i]}`}
            </span>
          )}
        </span>
      ))}
      {unit && <span className="muted">{unit}</span>}
      <span className="muted">· slider hours are from departure; truck marker follows the selected route</span>
    </div>
  );
}

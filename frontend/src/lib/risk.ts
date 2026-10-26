import type { HeatMetric, RiskLabel, RiskLevel } from "./types";

export const RISK_LABELS: RiskLabel[] = ["Low", "Moderate", "High", "Severe", "No Travel"];

/** One color per risk level, used everywhere (routes, checkpoints, heatmap, legend). */
export const RISK_COLORS: Record<RiskLevel, string> = {
  0: "#2e9d5b",
  1: "#e3b51b",
  2: "#ef7d1a",
  3: "#d7263d",
  4: "#6b1d8f",
};

export const RISK_RGB: [number, number, number][] = Object.values(RISK_COLORS).map((hex) => [
  parseInt(hex.slice(1, 3), 16),
  parseInt(hex.slice(3, 5), 16),
  parseInt(hex.slice(5, 7), 16),
]);

export function riskColor(level: number): string {
  return RISK_COLORS[Math.max(0, Math.min(4, Math.round(level))) as RiskLevel];
}

/** Band thresholds from the assessment's risk table (lower bound of Moderate..No Travel). */
export const METRIC_THRESHOLDS: Record<Exclude<HeatMetric, "risk">, number[]> = {
  wind: [25, 35, 45, 55],
  rain: [0.1, 0.25, 0.5, 1.0],
  snow: [0.5, 1.0, 2.0, 3.0],
};

export const METRIC_INFO: Record<HeatMetric, { label: string; unit: string }> = {
  risk: { label: "Risk (load-adjusted)", unit: "" },
  wind: { label: "Wind", unit: "mph" },
  rain: { label: "Rain", unit: "in/hr" },
  snow: { label: "Snow", unit: "in/hr" },
};

/**
 * Map a raw weather value onto the 0..4 risk scale so every metric shares one
 * palette. A value inside band k maps to k + fraction-through-the-band, so
 * colors change at the same thresholds the risk rules use.
 */
export function toRiskScale(metric: HeatMetric, value: number): number {
  if (metric === "risk") return value;
  const t = METRIC_THRESHOLDS[metric];
  const bounds = [0, ...t, t[3] * 1.5];
  for (let k = 0; k < 5; k++) {
    if (value < bounds[k + 1]) {
      return k + (value - bounds[k]) / (bounds[k + 1] - bounds[k]);
    }
  }
  return 4.99;
}

export function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return h ? `${h}h ${m.toString().padStart(2, "0")}m` : `${m}m`;
}

const timeFmt = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  hour: "numeric",
  minute: "2-digit",
  timeZoneName: "short",
});

export function formatTime(iso: string): string {
  return timeFmt.format(new Date(iso));
}

export function formatMiles(mi: number): string {
  return `${Math.round(mi).toLocaleString()} mi`;
}

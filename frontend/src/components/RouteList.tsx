"use client";

import { RISK_COLORS, RISK_LABELS, formatDuration, formatMiles, formatTime, riskColor } from "@/lib/risk";
import type { Plan, RiskLevel, Route } from "@/lib/types";

interface Props {
  plan: Plan;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function RouteList({ plan, selectedId, onSelect }: Props) {
  const ranked = [...plan.routes].sort((a, b) => a.rank - b.rank);
  return (
    <section className="routes" aria-label="Route options">
      <div className={`recommendation${plan.no_travel_warning ? " danger" : ""}`}>
        {plan.no_travel_warning ? (
          <>
            <strong>Every route has No Travel conditions.</strong> Consider delaying departure. The least-bad option
            is ranked first.
          </>
        ) : (
          plan.recommendation_reason
        )}
      </div>
      {plan.routes.length < 3 && (
        <p className="muted small">Only {plan.routes.length} distinct practical route(s) exist for this trip.</p>
      )}
      {ranked.map((r) => (
        <RouteCard key={r.id} route={r} selected={r.id === selectedId} onSelect={onSelect} />
      ))}
    </section>
  );
}

function RouteCard({ route, selected, onSelect }: { route: Route; selected: boolean; onSelect: (id: string) => void }) {
  const s = route.summary;
  return (
    <button
      type="button"
      className={`route-card${selected ? " selected" : ""}`}
      aria-pressed={selected}
      onClick={() => onSelect(route.id)}
    >
      <div className="route-card-head">
        <span className="rank">#{route.rank}</span>
        <span className="route-name" title={route.name}>
          {route.name}
        </span>
        {route.recommended && <span className="badge">Recommended</span>}
      </div>

      <div className="route-stats">
        <Stat label="Distance" value={formatMiles(route.distance_mi)} />
        <Stat label="Drive time" value={formatDuration(route.duration_s)} />
        <Stat label="Arrive" value={formatTime(route.arrival)} />
      </div>

      <RiskBar summary={s.miles_by_risk} total={route.distance_mi} />

      <div className="route-stats">
        <Stat label="Severe+ mi" value={s.severe_miles.toFixed(0)} tone={s.severe_miles > 0 ? 3 : undefined} />
        <Stat label="High mi" value={s.high_miles.toFixed(0)} tone={s.high_miles > 0 ? 2 : undefined} />
        <Stat label="Avg risk" value={`${s.average_risk.toFixed(2)} / 4`} />
        <Stat label="Worst" value={s.max_risk_label} tone={s.max_risk} />
      </div>
    </button>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: RiskLevel }) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <span className="stat-value" style={tone != null && tone > 0 ? { color: riskColor(tone) } : undefined}>
        {value}
      </span>
    </div>
  );
}

function RiskBar({ summary, total }: { summary: Record<string, number>; total: number }) {
  return (
    <div className="risk-bar" role="img" aria-label={RISK_LABELS.map((l) => `${l} ${summary[l].toFixed(0)} mi`).join(", ")}>
      {RISK_LABELS.map((label, i) =>
        summary[label] > 0 ? (
          <span
            key={label}
            style={{ width: `${(summary[label] / total) * 100}%`, background: RISK_COLORS[i as RiskLevel] }}
            title={`${label}: ${summary[label].toFixed(0)} mi`}
          />
        ) : null,
      )}
    </div>
  );
}

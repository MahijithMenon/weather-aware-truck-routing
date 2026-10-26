"use client";

import { useState } from "react";
import { formatTime, riskColor } from "@/lib/risk";
import type { Route } from "@/lib/types";

/** Checkpoint table for the selected route, optionally filtered to elevated risk. */
export function CheckpointList({ route }: { route: Route }) {
  const [onlyRisky, setOnlyRisky] = useState(false);
  const risky = route.checkpoints.filter((c) => c.risk > 0);
  const rows = onlyRisky ? risky : route.checkpoints;

  return (
    <section className="checkpoints" aria-label="Checkpoints">
      <div className="section-head">
        <h2>
          Checkpoints <span className="muted">({route.checkpoints.length})</span>
        </h2>
        <label className="toggle">
          <input type="checkbox" checked={onlyRisky} onChange={(e) => setOnlyRisky(e.target.checked)} />
          Only elevated risk ({risky.length})
        </label>
      </div>
      {rows.length === 0 ? (
        <p className="muted small">No checkpoints above Low risk on this route.</p>
      ) : (
        <div className="cp-table-wrap">
          <table className="cp-table">
            <thead>
              <tr>
                <th>Mile</th>
                <th>ETA</th>
                <th>Wind</th>
                <th>Rain</th>
                <th>Snow</th>
                <th>Risk</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.index} title={c.reasons.join(" · ") || undefined}>
                  <td>{Math.round(c.mile)}</td>
                  <td className="nowrap">{formatTime(c.eta)}</td>
                  <td>{c.weather ? `${c.weather.wind_mph.toFixed(0)}` : "–"}</td>
                  <td>{c.weather ? c.weather.rain_in_hr.toFixed(2) : "–"}</td>
                  <td>{c.weather ? c.weather.snow_in_hr.toFixed(2) : "–"}</td>
                  <td>
                    <span className="risk-chip" style={{ background: riskColor(c.risk) }}>
                      {c.risk_label}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">Wind in mph, precipitation in in/hr, at the truck&apos;s ETA.</p>
        </div>
      )}
    </section>
  );
}

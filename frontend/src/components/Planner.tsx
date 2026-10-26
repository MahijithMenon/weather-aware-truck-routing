"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import { fetchHeatmap, planTrip } from "@/lib/api";
import type { HeatMetric, Heatmap, Plan, TripInput } from "@/lib/types";
import { CheckpointList } from "./CheckpointList";
import { HeatmapControls } from "./HeatmapControls";
import { RouteList } from "./RouteList";
import { TripForm } from "./TripForm";

// Leaflet touches `window` on import, so the map renders client-side only.
const MapView = dynamic(() => import("./map/MapView"), {
  ssr: false,
  loading: () => <div className="map map-loading">Loading map…</div>,
});

export function Planner() {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [planning, setPlanning] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const [heatmap, setHeatmap] = useState<Heatmap | null>(null);
  const [heatLoading, setHeatLoading] = useState(false);
  const [heatError, setHeatError] = useState<string | null>(null);
  const [heatHour, setHeatHour] = useState(0);
  const [heatMetric, setHeatMetric] = useState<HeatMetric>("risk");
  const [heatVisible, setHeatVisible] = useState(true);
  const [playing, setPlaying] = useState(false);

  const planCtrl = useRef<AbortController | null>(null);

  const submit = useCallback(async (input: TripInput) => {
    planCtrl.current?.abort();
    const ctrl = new AbortController();
    planCtrl.current = ctrl;
    setPlanning(true);
    setPlanError(null);
    setPlaying(false);
    try {
      const result = await planTrip(input, ctrl.signal);
      setPlan(result);
      setSelectedId(result.recommended_route_id);
      setHeatmap(null);
      setHeatHour(0);
    } catch (e) {
      if (!ctrl.signal.aborted) setPlanError((e as Error).message);
    } finally {
      if (!ctrl.signal.aborted) setPlanning(false);
    }
  }, []);

  // Routes render first; the corridor heatmap loads right after.
  useEffect(() => {
    if (!plan) return;
    const ctrl = new AbortController();
    setHeatLoading(true);
    setHeatError(null);
    fetchHeatmap(plan.plan_id, ctrl.signal)
      .then(setHeatmap)
      .catch((e: Error) => !ctrl.signal.aborted && setHeatError(e.message))
      .finally(() => !ctrl.signal.aborted && setHeatLoading(false));
    return () => ctrl.abort();
  }, [plan]);

  const selected = plan?.routes.find((r) => r.id === selectedId) ?? null;

  return (
    <div className="app">
      <aside className="sidebar">
        <header className="brand">
          <h1>Weather-Aware Truck Routing</h1>
          <p className="muted small">
            Three route options, scored by the forecast at each checkpoint when the truck gets there.
          </p>
        </header>

        <TripForm loading={planning} onSubmit={submit} />
        {planError && (
          <div className="form-error" role="alert">
            {planError}
          </div>
        )}

        {planning && !plan && <div className="placeholder">Fetching routes and checkpoint forecasts…</div>}

        {plan && (
          <div className={planning ? "stale" : undefined}>
            <RouteList plan={plan} selectedId={selectedId} onSelect={setSelectedId} />
            {selected && <CheckpointList route={selected} />}
          </div>
        )}

        <footer className="muted small credits">
          Routing © OSRM / OpenStreetMap · Weather © Open-Meteo · Geocoding © Photon
        </footer>
      </aside>

      <main className="map-area">
        <MapView
          plan={plan}
          selectedRouteId={selectedId}
          onSelectRoute={setSelectedId}
          heatmap={heatmap}
          heatHour={heatHour}
          heatMetric={heatMetric}
          heatVisible={heatVisible}
        />
        {plan && (
          <HeatmapControls
            heatmap={heatmap}
            loading={heatLoading}
            error={heatError}
            hour={heatHour}
            onHour={setHeatHour}
            metric={heatMetric}
            onMetric={setHeatMetric}
            visible={heatVisible}
            onVisible={setHeatVisible}
            playing={playing}
            onPlaying={setPlaying}
          />
        )}
        {planning && <div className="map-busy">Planning…</div>}
      </main>
    </div>
  );
}

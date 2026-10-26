"use client";

import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { memo, useEffect, useMemo, useRef } from "react";
import {
  CircleMarker,
  MapContainer,
  Polyline,
  Popup,
  TileLayer,
  Tooltip,
  useMap,
} from "react-leaflet";
import { positionAt, riskSegments } from "@/lib/geo";
import { formatTime, riskColor, toRiskScale } from "@/lib/risk";
import type { Checkpoint, HeatMetric, Heatmap, Plan, Route } from "@/lib/types";
import { RiskHeatLayer } from "./RiskHeatLayer";

export interface MapViewProps {
  plan: Plan | null;
  selectedRouteId: string | null;
  onSelectRoute: (id: string) => void;
  heatmap: Heatmap | null;
  heatHour: number;
  heatMetric: HeatMetric;
  heatVisible: boolean;
}

const US_CENTER: [number, number] = [39.5, -98.35];

export default function MapView(props: MapViewProps) {
  const { plan, selectedRouteId, onSelectRoute, heatmap, heatHour, heatMetric, heatVisible } = props;
  const selected = plan?.routes.find((r) => r.id === selectedRouteId) ?? null;
  // Draw the selected route last so it sits on top.
  const others = plan?.routes.filter((r) => r.id !== selectedRouteId) ?? [];

  const truckElapsed = useMemo(() => {
    if (!plan || !heatmap) return null;
    return (Date.parse(heatmap.hours[heatHour]) - Date.parse(plan.departure)) / 1000;
  }, [plan, heatmap, heatHour]);

  return (
    <MapContainer
      center={US_CENTER}
      zoom={4}
      minZoom={3}
      maxZoom={18}
      preferCanvas
      className="map"
      zoomControl={false}
      worldCopyJump
    >
      <TileLayer
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        maxZoom={18}
        className="basemap"
        keepBuffer={4}
      />
      <AutoResize />
      <ZoomControl />
      {heatmap && heatVisible && <HeatLayer heatmap={heatmap} hour={heatHour} metric={heatMetric} />}

      {plan && <FitToPlan plan={plan} />}

      {others.map((r) => (
        <InactiveRoute key={r.id} route={r} onSelect={onSelectRoute} />
      ))}
      {selected && <ActiveRoute key={selected.id} route={selected} />}

      {plan && (
        <>
          <Endpoint lat={plan.origin.lat} lon={plan.origin.lon} label={`Origin: ${plan.origin.name}`} color="#1f2937" />
          <Endpoint
            lat={plan.destination.lat}
            lon={plan.destination.lon}
            label={`Destination: ${plan.destination.name}`}
            color="#2563eb"
          />
        </>
      )}

      {selected && truckElapsed != null && <Truck checkpoints={selected.checkpoints} elapsedS={truckElapsed} />}
    </MapContainer>
  );
}

/**
 * Leaflet measures its container once and only re-measures on window resize.
 * Watch the container itself so layout changes (breakpoints, panels, the
 * dynamic import finishing before CSS settles) never leave grey, unloaded areas.
 */
function AutoResize() {
  const map = useMap();
  useEffect(() => {
    const observer = new ResizeObserver(() => map.invalidateSize({ pan: false }));
    observer.observe(map.getContainer());
    return () => observer.disconnect();
  }, [map]);
  return null;
}

function ZoomControl() {
  const map = useMap();
  useEffect(() => {
    const control = L.control.zoom({ position: "topright" }).addTo(map);
    return () => {
      control.remove();
    };
  }, [map]);
  return null;
}

function FitToPlan({ plan }: { plan: Plan }) {
  const map = useMap();
  useEffect(() => {
    const bounds = L.latLngBounds(plan.routes.flatMap((r) => r.geometry));
    // Extra bottom padding keeps the routes clear of the heatmap control panel.
    const narrow = map.getSize().x < 600;
    map.flyToBounds(bounds, {
      paddingTopLeft: [40, 40],
      paddingBottomRight: [60, narrow ? 190 : 170],
      duration: 0.8,
    });
  }, [map, plan]);
  return null;
}

const InactiveRoute = memo(function InactiveRoute({
  route,
  onSelect,
}: {
  route: Route;
  onSelect: (id: string) => void;
}) {
  const handlers = useMemo(() => ({ click: () => onSelect(route.id) }), [onSelect, route.id]);
  return (
    <>
      <Polyline positions={route.geometry} pathOptions={{ color: "#64748b", weight: 9, opacity: 0.001 }} eventHandlers={handlers}>
        <Tooltip sticky>
          #{route.rank} {route.name} - click to select
        </Tooltip>
      </Polyline>
      <Polyline
        positions={route.geometry}
        pathOptions={{ color: "#64748b", weight: 4, opacity: 0.55, dashArray: "6 6" }}
        eventHandlers={handlers}
      />
      {route.checkpoints.map((c) => (
        <CircleMarker
          key={c.index}
          center={[c.lat, c.lon]}
          radius={3}
          pathOptions={{ color: "#fff", weight: 1, fillColor: riskColor(c.risk), fillOpacity: 0.8 }}
          eventHandlers={handlers}
        >
          <CheckpointPopup checkpoint={c} routeName={route.name} />
        </CircleMarker>
      ))}
    </>
  );
});

const ActiveRoute = memo(function ActiveRoute({ route }: { route: Route }) {
  const segments = useMemo(() => riskSegments(route), [route]);
  return (
    <>
      <Polyline positions={route.geometry} pathOptions={{ color: "#0f172a", weight: 9, opacity: 0.85 }} interactive={false} />
      {segments.map((s, i) => (
        <Polyline key={i} positions={s.points} pathOptions={{ color: riskColor(s.risk), weight: 5, opacity: 1 }} interactive={false} />
      ))}
      {route.checkpoints.map((c) => (
        <CircleMarker
          key={c.index}
          center={[c.lat, c.lon]}
          radius={6}
          pathOptions={{ color: "#0f172a", weight: 1.5, fillColor: riskColor(c.risk), fillOpacity: 1 }}
        >
          <Tooltip direction="top" offset={[0, -6]}>
            Mile {Math.round(c.mile)} · {c.risk_label} · {formatTime(c.eta)}
          </Tooltip>
          <CheckpointPopup checkpoint={c} routeName={route.name} />
        </CircleMarker>
      ))}
    </>
  );
});

function CheckpointPopup({ checkpoint: c, routeName }: { checkpoint: Checkpoint; routeName: string }) {
  const wx = c.weather;
  return (
    <Popup>
      <div className="cp-popup">
        <div className="cp-popup-head">
          <span className="risk-chip" style={{ background: riskColor(c.risk) }}>
            {c.risk_label}
          </span>
          <strong>Mile {Math.round(c.mile)}</strong>
        </div>
        <div className="muted">{routeName}</div>
        <div>ETA {formatTime(c.eta)}</div>
        {wx ? (
          <table>
            <tbody>
              <tr>
                <td>Wind</td>
                <td>
                  {wx.wind_mph.toFixed(0)} mph{wx.gust_mph != null && ` (gusts ${wx.gust_mph.toFixed(0)})`}
                </td>
                <td>{wx.wind_risk}</td>
              </tr>
              <tr>
                <td>Rain</td>
                <td>{wx.rain_in_hr.toFixed(2)} in/hr</td>
                <td>{wx.rain_risk}</td>
              </tr>
              <tr>
                <td>Snow</td>
                <td>{wx.snow_in_hr.toFixed(2)} in/hr</td>
                <td>{wx.snow_risk}</td>
              </tr>
              {wx.temp_f != null && (
                <tr>
                  <td>Temp</td>
                  <td>{wx.temp_f.toFixed(0)}°F</td>
                  <td />
                </tr>
              )}
            </tbody>
          </table>
        ) : (
          <div className="muted">No forecast data</div>
        )}
        {c.reasons.length > 0 && <div className="cp-reasons">{c.reasons.join(" · ")}</div>}
      </div>
    </Popup>
  );
}

function Endpoint({ lat, lon, label, color }: { lat: number; lon: number; label: string; color: string }) {
  return (
    <CircleMarker center={[lat, lon]} radius={9} pathOptions={{ color: "#fff", weight: 3, fillColor: color, fillOpacity: 1 }}>
      <Tooltip direction="top" offset={[0, -8]}>
        {label}
      </Tooltip>
    </CircleMarker>
  );
}

function Truck({ checkpoints, elapsedS }: { checkpoints: Checkpoint[]; elapsedS: number }) {
  const pos = positionAt(checkpoints, elapsedS);
  if (!pos) return null;
  return (
    <CircleMarker center={pos} radius={8} pathOptions={{ color: "#0f172a", weight: 3, fillColor: "#fff", fillOpacity: 1 }}>
      <Tooltip direction="right" offset={[10, 0]} permanent className="truck-tip">
        Truck
      </Tooltip>
    </CircleMarker>
  );
}

function HeatLayer({ heatmap, hour, metric }: { heatmap: Heatmap; hour: number; metric: HeatMetric }) {
  const map = useMap();
  const layerRef = useRef<RiskHeatLayer | null>(null);

  useEffect(() => {
    const layer = new RiskHeatLayer().addTo(map);
    layerRef.current = layer;
    return () => {
      layer.remove();
      layerRef.current = null;
    };
  }, [map]);

  useEffect(() => {
    // Blend radius: a bit over the sample spacing so the corridor reads as continuous.
    layerRef.current?.setSamples(heatmap.points, heatmap.spacing_mi * 1.35);
  }, [heatmap]);

  useEffect(() => {
    const values = heatmap.points.map((p) => {
      const v = p[metric][hour];
      return v == null ? null : toRiskScale(metric, v);
    });
    // Precipitation is zero almost everywhere; keep dry areas nearly clear so
    // the bands that matter stand out. Risk and wind show the whole corridor.
    layerRef.current?.setValues(values, metric === "rain" || metric === "snow" ? 0.04 : 0.3);
  }, [heatmap, hour, metric]);

  return null;
}

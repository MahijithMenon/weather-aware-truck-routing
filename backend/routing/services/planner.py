"""Trip planning: route options -> weather checkpoints -> risk -> recommendation."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.core.cache import cache

from . import providers
from .geo import LatLon, Polyline, bearing_deg, destination, haversine_mi, simplify_for_display
from .risk import RISK_LABELS, Risk, assess, explain_choice, ranking_key, summarize_segments

ROUTE_COUNT = 3
# Drop generated alternatives that are much longer or slower than the fastest route.
MAX_DISTANCE_RATIO = 1.5
MAX_DURATION_RATIO = 1.5
HEATMAP_HOURS = 48
PLAN_TTL_S = 30 * 60


class PlanningError(Exception):
    pass


@dataclass(frozen=True)
class TripRequest:
    origin: providers.Place
    destination: providers.Place
    departure: datetime  # timezone-aware
    load_lb: float
    interval_mi: int


# --------------------------------------------------------------------------- route options


def _sample(line: Polyline, n: int) -> list[LatLon]:
    return [line.at_mile(line.length_mi * i / (n - 1))[0] for i in range(n)]


def _overlap(a: Polyline, b: Polyline, tolerance_mi: float = 1.5) -> float:
    """Share of `b` that runs within `tolerance_mi` of `a` (sampled)."""
    a_pts = _sample(a, max(50, int(a.length_mi / 2)))
    b_pts = _sample(b, 40)
    near = sum(1 for p in b_pts if min(haversine_mi(p, q) for q in a_pts) <= tolerance_mi)
    return near / len(b_pts)


def _is_distinct(candidate: Polyline, chosen: list[Polyline]) -> bool:
    return all(_overlap(c, candidate) < 0.9 and _overlap(candidate, c) < 0.9 for c in chosen)


def _detour_waypoints(origin: LatLon, dest: LatLon, spread: float = 0.15) -> list[LatLon]:
    """Via points offset to either side of the straight origin-destination line.

    Using the straight line (not the fastest route) means the detour requests
    don't depend on the first OSRM response, so they can all run in parallel.
    """
    crow_mi = haversine_mi(origin, dest)
    offset = min(max(crow_mi * spread, 5.0), 120.0)
    heading = bearing_deg(origin, dest)
    vias = []
    for frac, side in ((0.5, 90), (0.5, -90), (0.33, 90), (0.66, -90)):
        along = destination(origin, heading, crow_mi * frac)
        vias.append(destination(along, heading + side, offset))
    return vias


def route_options(origin: LatLon, dest: LatLon) -> list[providers.RawRoute]:
    """Up to three meaningfully different routes.

    OSRM's own alternatives come first. The public server returns at most two,
    so the rest are built by routing through a via point offset to either side
    of the direct line, keeping only results that are distinct and not
    absurdly long. All requests run concurrently.
    """
    with ThreadPoolExecutor(max_workers=5) as pool:
        main_future = pool.submit(providers.osrm_routes, [origin, dest], ROUTE_COUNT)
        detours = pool.map(_safe_route, ([origin, v, dest] for v in _detour_waypoints(origin, dest)))
        routes = main_future.result()
        if not routes:
            raise PlanningError("No drivable route found between these locations.")
        chosen = _pick_distinct([], routes + list(detours), routes[0].line)
        if len(chosen) < ROUTE_COUNT:
            # Wide detours were rejected (too long, or same corridor): try closer ones.
            closer = pool.map(_safe_route, ([origin, v, dest] for v in _detour_waypoints(origin, dest, 0.07)))
            chosen = _pick_distinct(chosen, list(closer), routes[0].line)
    return chosen


def _pick_distinct(
    chosen: list[providers.RawRoute], candidates: list[providers.RawRoute | None], fastest: Polyline
) -> list[providers.RawRoute]:
    chosen = list(chosen)
    for cand in candidates:
        if len(chosen) == ROUTE_COUNT:
            break
        if cand is None:
            continue
        if cand.line.length_mi > fastest.length_mi * MAX_DISTANCE_RATIO:
            continue
        if cand.line.duration_s > fastest.duration_s * MAX_DURATION_RATIO:
            continue
        if _is_distinct(cand.line, [c.line for c in chosen]):
            chosen.append(cand)
    return chosen


def _safe_route(waypoints: list[LatLon]) -> providers.RawRoute | None:
    try:
        found = providers.osrm_routes(waypoints)
    except providers.ProviderError:
        return None
    return found[0] if found else None


# --------------------------------------------------------------------------- checkpoints


def checkpoint_miles(length_mi: float, interval_mi: float) -> list[float]:
    """0, interval, 2*interval, ... plus the destination itself."""
    miles = []
    m = 0.0
    while m < length_mi - 0.5:  # skip a sliver checkpoint right before arrival
        miles.append(m)
        m += interval_mi
    miles.append(length_mi)
    return miles


def segments_from_checkpoints(miles: list[float], risks: list[Risk]) -> list[tuple[float, Risk]]:
    """Each checkpoint stands for the road halfway to its neighbours.

    So the stretch between two checkpoints is split at its midpoint, with each
    half taking the risk of the nearer checkpoint.
    """
    segments = []
    for i in range(len(miles) - 1):
        half = (miles[i + 1] - miles[i]) / 2
        segments.append((half, risks[i]))
        segments.append((half, risks[i + 1]))
    return segments


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _build_route(idx: int, raw: providers.RawRoute, trip: TripRequest, forecasts, miles) -> dict:
    line = raw.line
    checkpoints = []
    risks: list[Risk] = []
    for n, (mile, series) in enumerate(zip(miles, forecasts)):
        pos, elapsed = line.at_mile(mile)
        eta = trip.departure + timedelta(seconds=round(elapsed))
        wx = series.at(eta)
        if wx is None or wx["wind_mph"] is None:
            risk, reasons, wx_out = Risk.LOW, ["No forecast available for this time"], None
        else:
            a = assess(wx["wind_mph"], wx["rain_in_hr"] or 0.0, wx["snow_in_hr"] or 0.0, trip.load_lb)
            risk, reasons = a.risk, list(a.reasons)
            wx_out = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in wx.items()}
            wx_out.update(
                wind_risk=a.wind_risk.label, rain_risk=a.rain_risk.label, snow_risk=a.snow_risk.label
            )
        risks.append(risk)
        checkpoints.append(
            {
                "index": n,
                "mile": round(mile, 1),
                "lat": round(pos[0], 5),
                "lon": round(pos[1], 5),
                "eta": _iso(eta),
                "elapsed_s": round(elapsed),
                "risk": int(risk),
                "risk_label": risk.label,
                "reasons": reasons,
                "weather": wx_out,
            }
        )

    summary = summarize_segments(segments_from_checkpoints(miles, risks), line.duration_s)
    return {
        "id": f"route-{idx}",
        "name": raw.name or f"Route {idx + 1}",
        "distance_mi": round(line.length_mi, 1),
        "duration_s": round(line.duration_s),
        "arrival": _iso(trip.departure + timedelta(seconds=line.duration_s)),
        "geometry": [[round(lat, 5), round(lon, 5)] for lat, lon in simplify_for_display(line.points)],
        "checkpoints": checkpoints,
        "summary": {
            "miles_by_risk": {RISK_LABELS[r]: round(m, 1) for r, m in summary.miles_by_risk.items()},
            "severe_miles": round(summary.severe_miles, 1),
            "high_miles": round(summary.high_miles, 1),
            "no_travel_miles": round(summary.no_travel_miles, 1),
            "average_risk": round(summary.average_risk, 2),
            "max_risk": int(max(risks)),
            "max_risk_label": max(risks).label,
        },
        "_summary": summary,
        "_line": line,
    }


def plan_trip(trip: TripRequest) -> dict:
    origin = (trip.origin.lat, trip.origin.lon)
    dest = (trip.destination.lat, trip.destination.lon)
    raw_routes = route_options(origin, dest)

    # Gather every checkpoint on every route, then fetch weather in one pass.
    per_route_miles = [checkpoint_miles(r.line.length_mi, trip.interval_mi) for r in raw_routes]
    points = [r.line.at_mile(m)[0] for r, miles in zip(raw_routes, per_route_miles) for m in miles]
    longest_s = max(r.line.duration_s for r in raw_routes)
    start = trip.departure - timedelta(hours=1)
    end = trip.departure + timedelta(seconds=longest_s, hours=2)
    forecasts = providers.hourly_forecasts(points, start, end)

    routes = []
    offset = 0
    for idx, (raw, miles) in enumerate(zip(raw_routes, per_route_miles)):
        routes.append(_build_route(idx, raw, trip, forecasts[offset : offset + len(miles)], miles))
        offset += len(miles)

    ranked = sorted(routes, key=lambda r: ranking_key(r["_summary"]))
    for rank, r in enumerate(ranked, start=1):
        r["rank"] = rank
        r["recommended"] = rank == 1
    best = ranked[0]
    reason = explain_choice(best["_summary"], ranked[1]["_summary"] if len(ranked) > 1 else None)

    plan_id = uuid.uuid4().hex
    cache.set(
        f"plan:{plan_id}",
        {"lines": [r["_line"] for r in routes], "departure": trip.departure, "load_lb": trip.load_lb},
        PLAN_TTL_S,
    )
    for r in routes:
        del r["_summary"], r["_line"]

    return {
        "plan_id": plan_id,
        "origin": vars(trip.origin),
        "destination": vars(trip.destination),
        "departure": _iso(trip.departure),
        "load_lb": trip.load_lb,
        "interval_mi": trip.interval_mi,
        "routes": routes,
        "recommended_route_id": best["id"],
        "recommendation_reason": reason,
        "no_travel_warning": all(r["summary"]["no_travel_miles"] > 0 for r in routes),
    }


# --------------------------------------------------------------------------- heatmap


def corridor_points(lines: list[Polyline], max_points: int = 320) -> tuple[list[LatLon], float]:
    """A band of sample points along and either side of every route.

    Returns the points and their typical spacing in miles (the frontend uses it
    as the blending radius when it interpolates the heatmap).
    """
    longest = max(line.length_mi for line in lines)
    band = min(max(longest * 0.08, 12.0), 45.0)  # half-width of the corridor in miles
    offsets = (-band, -band / 2, 0.0, band / 2, band)
    per_route = max_points // (len(lines) * len(offsets))
    spacing = max(longest / max(per_route - 1, 1), band / 2)

    grid = band / 2 / 69.0  # snap spacing in degrees so overlapping routes share points
    seen: dict[tuple[int, int], LatLon] = {}
    for line in lines:
        n = max(int(line.length_mi / spacing) + 1, 2)
        for i in range(n):
            mile = line.length_mi * i / (n - 1)
            pos, _ = line.at_mile(mile)
            heading = line.bearing_at_mile(mile, window_mi=max(2.0, spacing / 2))
            for off in offsets:
                p = destination(pos, heading + 90, off) if off else pos
                key = (round(p[0] / grid), round(p[1] / grid))
                seen.setdefault(key, p)
    return list(seen.values()), max(spacing, band / 2)


def heatmap(plan_id: str) -> dict:
    plan = cache.get(f"plan:{plan_id}")
    if plan is None:
        raise PlanningError("This plan has expired. Please plan the trip again.")
    departure: datetime = plan["departure"]
    start = departure.replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=HEATMAP_HOURS)

    points, spacing_mi = corridor_points(plan["lines"])
    forecasts = providers.hourly_forecasts(points, start, end)
    hours = [start + timedelta(hours=h) for h in range(HEATMAP_HOURS + 1)]

    def col(values, i, digits):
        v = values[i] if i < len(values) else None
        return None if v is None else round(v, digits)

    cells = []
    for p, s in zip(points, forecasts):
        risk, wind, rain, snow = [], [], [], []
        for h in range(len(hours)):
            w, r, sn = col(s.wind_mph, h, 1), col(s.rain_in, h, 2), col(s.snow_in, h, 2)
            wind.append(w)
            rain.append(r)
            snow.append(sn)
            risk.append(None if w is None else int(assess(w, r or 0.0, sn or 0.0, plan["load_lb"]).risk))
        cells.append(
            {"lat": round(p[0], 4), "lon": round(p[1], 4), "risk": risk, "wind": wind, "rain": rain, "snow": snow}
        )
    return {
        "plan_id": plan_id,
        "hours": [_iso(h) for h in hours],
        "spacing_mi": round(spacing_mi, 1),
        "points": cells,
    }

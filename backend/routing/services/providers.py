"""Thin clients for the third-party APIs: Photon (geocoding), OSRM (routing),
Open-Meteo (weather). Everything provider-specific lives here."""

from __future__ import annotations

import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone

import requests
from django.conf import settings
from django.core.cache import cache

from .geo import LatLon, Polyline, decode_polyline, haversine_mi

log = logging.getLogger(__name__)

TIMEOUT_S = 20
# Commercial trucks are governed well below car speeds on many highways; OSRM's
# public server only has a car profile, so cap every segment at this speed.
TRUCK_MAX_MPH = 65.0

_session = requests.Session()
_session.headers["User-Agent"] = settings.HTTP_USER_AGENT


class ProviderError(Exception):
    """A third-party API failed or returned something unusable."""


# --------------------------------------------------------------------------- geocoding


@dataclass(frozen=True)
class Place:
    name: str
    lat: float
    lon: float


def _place_label(props: dict) -> str:
    parts = [props.get("name")]
    for key in ("city", "state", "country"):
        value = props.get(key)
        if value and value not in parts:
            parts.append(value)
    return ", ".join(p for p in parts if p)


def geocode(query: str, limit: int = 6) -> list[Place]:
    key = "geo:" + hashlib.sha1(f"{query.lower()}|{limit}".encode()).hexdigest()
    if (hit := cache.get(key)) is not None:
        return hit
    try:
        resp = _session.get(
            settings.PHOTON_URL, params={"q": query, "limit": limit, "lang": "en"}, timeout=TIMEOUT_S
        )
        resp.raise_for_status()
        features = resp.json().get("features", [])
    except (requests.RequestException, ValueError) as exc:
        raise ProviderError(f"Geocoding failed: {exc}") from exc
    places = [
        Place(_place_label(f["properties"]), f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0])
        for f in features
        if f.get("geometry", {}).get("type") == "Point"
    ]
    cache.set(key, places, 24 * 3600)
    return places


def reverse_geocode(lat: float, lon: float) -> Place:
    """Readable label for the user's own coordinates (e.g. "W Adams St, Chicago, Illinois").

    The nearest OSM feature is often a shop or restaurant, so the label is built
    from street/city/state instead of its name. The returned point is always the
    caller's exact position, not the feature's.
    """
    key = f"rev:{lat:.4f},{lon:.4f}"
    if (hit := cache.get(key)) is not None:
        return hit
    fallback = Place(f"Current location ({lat:.4f}, {lon:.4f})", lat, lon)
    try:
        resp = _session.get(
            settings.PHOTON_URL.replace("/api/", "/reverse"),
            params={"lat": lat, "lon": lon, "limit": 1, "lang": "en"},
            timeout=TIMEOUT_S,
        )
        resp.raise_for_status()
        features = resp.json().get("features", [])
    except (requests.RequestException, ValueError) as exc:
        log.warning("reverse geocoding failed: %s", exc)
        return fallback
    if not features:
        return fallback
    props = features[0]["properties"]
    parts = [props.get("street"), props.get("city") or props.get("county"), props.get("state")]
    label = ", ".join(dict.fromkeys(p for p in parts if p))
    place = Place(f"Current location: {label}" if label else fallback.name, lat, lon)
    cache.set(key, place, 24 * 3600)
    return place


# --------------------------------------------------------------------------- routing


@dataclass
class RawRoute:
    name: str
    line: Polyline


def _route_from_osrm(route: dict) -> RawRoute:
    points = decode_polyline(route["geometry"])
    # Segment lengths come from the geometry itself; asking OSRM for distance
    # annotations too roughly doubles the response size.
    seg_mi = [haversine_mi(points[i], points[i + 1]) for i in range(len(points) - 1)]
    # Per-segment duration annotations, concatenated over legs. With
    # overview=full these line up with the geometry's segments.
    seg_s = [s for leg in route["legs"] for s in (leg.get("annotation") or {}).get("duration", [])]
    if len(seg_s) != len(seg_mi):
        # Fall back to spreading the total duration over distance.
        total = sum(seg_mi) or 1.0
        seg_s = [route["duration"] * m / total for m in seg_mi]

    cum_mi = [0.0]
    cum_s = [0.0]
    for miles, s in zip(seg_mi, seg_s):
        truck_s = max(s, miles / TRUCK_MAX_MPH * 3600)
        cum_mi.append(cum_mi[-1] + miles)
        cum_s.append(cum_s[-1] + truck_s)

    names = [leg.get("summary", "") for leg in route["legs"]]
    name = ", ".join(dict.fromkeys(n for part in names for n in part.split(", ") if n))
    return RawRoute(name=name, line=Polyline(points, cum_mi, cum_s))


OSRM_ATTEMPTS = 2
OSRM_READ_TIMEOUT_S = 25


def osrm_routes(waypoints: list[LatLon], alternatives: int = 0) -> list[RawRoute]:
    coords = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in waypoints)
    params = {
        "overview": "full",
        "geometries": "polyline",
        "annotations": "duration",
        "steps": "true",  # needed for the leg summary (road names)
        "alternatives": str(alternatives) if alternatives else "false",
    }
    url = f"{settings.OSRM_URL}/route/v1/driving/{coords}"
    key = "osrm:" + hashlib.sha1((url + repr(sorted(params.items()))).encode()).hexdigest()
    if (hit := cache.get(key)) is not None:
        return hit
    data = None
    for attempt in range(OSRM_ATTEMPTS):
        try:
            data = _session.get(url, params=params, timeout=(5, OSRM_READ_TIMEOUT_S)).json()
            break
        except (requests.RequestException, ValueError) as exc:
            # The public demo server's latency is erratic; one retry usually lands.
            log.warning("OSRM attempt %d failed: %s", attempt + 1, exc)
            if attempt == OSRM_ATTEMPTS - 1:
                raise ProviderError("Routing service is slow or unavailable, please try again.") from exc
    if data.get("code") != "Ok":
        if data.get("code") == "NoRoute":
            return []
        raise ProviderError(f"Routing failed: {data.get('message') or data.get('code')}")
    routes = []
    for r in data["routes"]:
        # Steps are only used for the summary; drop them before caching.
        for leg in r["legs"]:
            leg.pop("steps", None)
        routes.append(_route_from_osrm(r))
    cache.set(key, routes, 6 * 3600)
    return routes


# --------------------------------------------------------------------------- weather

HOURLY_VARS = ["wind_speed_10m", "wind_gusts_10m", "rain", "showers", "snowfall", "temperature_2m", "weather_code"]
BATCH_SIZE = 50


@dataclass
class HourlySeries:
    """Hourly forecast for one location, starting at `start` (UTC, on the hour)."""

    start: datetime
    wind_mph: list[float | None]
    gust_mph: list[float | None]
    rain_in: list[float | None]  # rain + showers, inches in the preceding hour
    snow_in: list[float | None]  # snowfall, inches in the preceding hour
    temp_f: list[float | None]
    weather_code: list[int | None]

    def __len__(self) -> int:
        return len(self.wind_mph)

    def at(self, when: datetime) -> dict | None:
        """Values linearly interpolated to `when`; None if outside the series."""
        offset_h = (when - self.start).total_seconds() / 3600
        if offset_h < 0 or offset_h > len(self) - 1:
            return None
        i = min(int(offset_h), len(self) - 2) if len(self) > 1 else 0
        frac = offset_h - i

        def lerp(values: list[float | None]) -> float | None:
            a = values[i]
            b = values[i + 1] if i + 1 < len(values) else a
            if a is None or b is None:
                return a if b is None else b
            return a + (b - a) * frac

        nearest = i if frac < 0.5 else min(i + 1, len(self) - 1)
        return {
            "wind_mph": lerp(self.wind_mph),
            "gust_mph": lerp(self.gust_mph),
            "rain_in_hr": lerp(self.rain_in),
            "snow_in_hr": lerp(self.snow_in),
            "temp_f": lerp(self.temp_f),
            "weather_code": self.weather_code[nearest],
        }


def _round_coord(p: LatLon) -> LatLon:
    # ~3 mile grid: well inside the forecast model resolution, and it makes
    # nearby checkpoints across the three routes share cache entries.
    return (round(p[0] * 20) / 20, round(p[1] * 20) / 20)


def _fetch_batch(points: list[LatLon], start: datetime, end: datetime) -> list[HourlySeries]:
    params = {
        "latitude": ",".join(f"{p[0]:.3f}" for p in points),
        "longitude": ",".join(f"{p[1]:.3f}" for p in points),
        "hourly": ",".join(HOURLY_VARS),
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "temperature_unit": "fahrenheit",
        "timezone": "GMT",
        "start_hour": start.strftime("%Y-%m-%dT%H:%M"),
        "end_hour": end.strftime("%Y-%m-%dT%H:%M"),
    }
    try:
        resp = _session.get(settings.OPEN_METEO_URL, params=params, timeout=TIMEOUT_S)
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise ProviderError(f"Weather lookup failed: {exc}") from exc
    if isinstance(data, dict) and data.get("error"):
        raise ProviderError(f"Weather lookup failed: {data.get('reason')}")
    items = data if isinstance(data, list) else [data]
    out = []
    for item in items:
        h = item["hourly"]
        rain = [
            None if r is None and s is None else (r or 0.0) + (s or 0.0)
            for r, s in zip(h["rain"], h["showers"])
        ]
        out.append(
            HourlySeries(
                start=start,
                wind_mph=h["wind_speed_10m"],
                gust_mph=h["wind_gusts_10m"],
                rain_in=rain,
                snow_in=h["snowfall"],
                temp_f=h["temperature_2m"],
                weather_code=h["weather_code"],
            )
        )
    return out


def hourly_forecasts(points: list[LatLon], start: datetime, end: datetime) -> list[HourlySeries]:
    """Hourly forecasts for many points between `start` and `end` (UTC, whole hours).

    Points are snapped to a small grid, de-duplicated, cached for 30 minutes and
    fetched in parallel batches (Open-Meteo accepts many coordinates per call).
    """
    start = start.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    end = end.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    window = f"{start:%Y%m%d%H}-{end:%Y%m%d%H}"
    snapped = [_round_coord(p) for p in points]
    unique = list(dict.fromkeys(snapped))

    def cache_key(p: LatLon) -> str:
        return f"wx:{p[0]:.2f},{p[1]:.2f}:{window}"

    cached = cache.get_many([cache_key(p) for p in unique])
    found: dict[LatLon, HourlySeries] = {p: cached[cache_key(p)] for p in unique if cache_key(p) in cached}
    missing = [p for p in unique if p not in found]

    batches = [missing[i : i + BATCH_SIZE] for i in range(0, len(missing), BATCH_SIZE)]
    if batches:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda b: _fetch_batch(b, start, end), batches))
        fresh: dict[str, HourlySeries] = {}
        for batch, series_list in zip(batches, results):
            for p, series in zip(batch, series_list):
                found[p] = series
                fresh[cache_key(p)] = series
        cache.set_many(fresh, 30 * 60)
        log.info("weather: %d points (%d cached, %d fetched)", len(unique), len(unique) - len(missing), len(missing))

    return [found[p] for p in snapped]

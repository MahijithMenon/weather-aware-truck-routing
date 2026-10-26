"""Small geometry helpers (no external GIS dependencies)."""

from __future__ import annotations

import bisect
import math

EARTH_RADIUS_MI = 3958.8
METERS_PER_MILE = 1609.344

LatLon = tuple[float, float]


def haversine_mi(a: LatLon, b: LatLon) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_MI * math.asin(math.sqrt(h))


def bearing_deg(a: LatLon, b: LatLon) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def destination(origin: LatLon, bearing: float, miles: float) -> LatLon:
    """Point reached travelling `miles` from `origin` on the given bearing."""
    lat1, lon1 = map(math.radians, origin)
    brng = math.radians(bearing)
    d = miles / EARTH_RADIUS_MI
    lat2 = math.asin(math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(brng))
    lon2 = lon1 + math.atan2(
        math.sin(brng) * math.sin(d) * math.cos(lat1), math.cos(d) - math.sin(lat1) * math.sin(lat2)
    )
    return (math.degrees(lat2), (math.degrees(lon2) + 540) % 360 - 180)


def decode_polyline(encoded: str, precision: int = 5) -> list[LatLon]:
    """Decode a Google encoded polyline into (lat, lon) pairs."""
    coords: list[LatLon] = []
    index = lat = lon = 0
    factor = 10**precision
    while index < len(encoded):
        for which in (0, 1):
            shift = result = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if which == 0:
                lat += delta
            else:
                lon += delta
        coords.append((lat / factor, lon / factor))
    return coords


class Polyline:
    """A route line with cumulative distance and time, for interpolation by mile."""

    def __init__(self, points: list[LatLon], cum_miles: list[float], cum_seconds: list[float]):
        assert len(points) == len(cum_miles) == len(cum_seconds) and len(points) >= 2
        self.points = points
        self.cum_miles = cum_miles
        self.cum_seconds = cum_seconds

    @property
    def length_mi(self) -> float:
        return self.cum_miles[-1]

    @property
    def duration_s(self) -> float:
        return self.cum_seconds[-1]

    def at_mile(self, mile: float) -> tuple[LatLon, float]:
        """Position and elapsed seconds at `mile` along the line (clamped to its ends)."""
        mile = min(max(mile, 0.0), self.length_mi)
        i = bisect.bisect_right(self.cum_miles, mile) - 1
        i = min(max(i, 0), len(self.points) - 2)
        m0, m1 = self.cum_miles[i], self.cum_miles[i + 1]
        t = 0.0 if m1 == m0 else (mile - m0) / (m1 - m0)
        (lat0, lon0), (lat1, lon1) = self.points[i], self.points[i + 1]
        pos = (lat0 + (lat1 - lat0) * t, lon0 + (lon1 - lon0) * t)
        secs = self.cum_seconds[i] + (self.cum_seconds[i + 1] - self.cum_seconds[i]) * t
        return pos, secs

    def bearing_at_mile(self, mile: float, window_mi: float = 2.0) -> float:
        a, _ = self.at_mile(mile - window_mi)
        b, _ = self.at_mile(mile + window_mi)
        return bearing_deg(a, b)


def simplify_for_display(points: list[LatLon], max_points: int = 1500) -> list[LatLon]:
    """Evenly thin a long polyline so the JSON payload and map render stay light."""
    if len(points) <= max_points:
        return points
    step = len(points) / (max_points - 1)
    out = [points[int(i * step)] for i in range(max_points - 1)]
    out.append(points[-1])
    return out

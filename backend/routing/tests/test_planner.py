from datetime import datetime, timedelta, timezone

import pytest

from routing.services.geo import Polyline, decode_polyline, haversine_mi
from routing.services.planner import checkpoint_miles, corridor_points, segments_from_checkpoints
from routing.services.providers import HourlySeries
from routing.services.risk import Risk


def test_checkpoint_miles_includes_start_and_destination():
    assert checkpoint_miles(60, 25) == [0, 25, 50, 60]
    assert checkpoint_miles(50.2, 25) == [0, 25, 50.2]  # no sliver checkpoint at 50
    assert checkpoint_miles(8, 10) == [0, 8]


def test_segments_split_at_midpoints():
    segs = segments_from_checkpoints([0, 10, 14], [Risk.LOW, Risk.HIGH, Risk.LOW])
    assert segs == [(5, Risk.LOW), (5, Risk.HIGH), (2, Risk.HIGH), (2, Risk.LOW)]
    assert sum(m for m, _ in segs) == 14


def test_decode_polyline_reference_example():
    # Example from Google's polyline algorithm documentation.
    pts = decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
    assert pts == [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]


def _line():
    pts = [(40.0, -100.0), (40.0, -99.0), (40.0, -98.0)]
    miles = [0.0, haversine_mi(pts[0], pts[1]), haversine_mi(pts[0], pts[1]) + haversine_mi(pts[1], pts[2])]
    return Polyline(pts, miles, [0.0, 3600.0, 7200.0])


def test_polyline_interpolates_position_and_time():
    line = _line()
    pos, secs = line.at_mile(line.length_mi / 4)
    assert pos[1] == pytest.approx(-99.5, abs=0.01)
    assert secs == pytest.approx(1800, rel=0.01)
    assert line.at_mile(10_000)[0] == (40.0, -98.0)  # clamped


def test_hourly_series_interpolates_to_eta():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    s = HourlySeries(start, [10, 20, 30], [0, 0, 0], [0, 0.2, 0], [0, 0, 0], [30, 30, 30], [0, 61, 0])
    wx = s.at(start + timedelta(minutes=30))
    assert wx["wind_mph"] == pytest.approx(15)
    assert wx["rain_in_hr"] == pytest.approx(0.1)
    assert wx["weather_code"] == 61  # nearest hour, not interpolated
    assert s.at(start - timedelta(hours=1)) is None
    assert s.at(start + timedelta(hours=3)) is None


def test_corridor_covers_both_sides_of_route():
    pts, spacing = corridor_points([_line()])
    assert spacing > 0
    lats = [p[0] for p in pts]
    assert min(lats) < 39.9 and max(lats) > 40.1
    assert len(pts) <= 320

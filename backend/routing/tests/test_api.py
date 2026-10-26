"""API tests with the third-party providers stubbed out (no network)."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from django.core.cache import cache
from django.test import Client

from routing.services import planner, providers
from routing.services.geo import Polyline, haversine_mi


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()


def _straight_route(name, lon_offset, hours):
    pts = [(40.0, -100.0), (40.0 + lon_offset, -99.0), (40.0, -98.0)]
    miles = [0.0]
    for a, b in zip(pts, pts[1:]):
        miles.append(miles[-1] + haversine_mi(a, b))
    return providers.RawRoute(name, Polyline(pts, miles, [0, hours * 1800, hours * 3600]))


def _series(start, wind):
    n = 80
    return providers.HourlySeries(start, [wind] * n, [wind] * n, [0.0] * n, [0.0] * n, [50.0] * n, [0] * n)


@pytest.fixture
def stub_providers(monkeypatch):
    fast_windy = _straight_route("Fast windy", 0.0, 2)
    slow_calm = _straight_route("Slow calm", 0.4, 3)

    monkeypatch.setattr(planner, "route_options", lambda o, d: [fast_windy, slow_calm])

    def forecasts(points, start, end):
        # Wind only near the straight line (lat ~40.0); the northern detour is calm.
        return [_series(start, 50.0 if abs(p[0] - 40.0) < 0.05 and -99.5 < p[1] < -98.5 else 5.0) for p in points]

    monkeypatch.setattr(providers, "hourly_forecasts", forecasts)


def _body(**overrides):
    departure = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    body = {
        "origin": {"name": "A", "lat": 40.0, "lon": -100.0},
        "destination": {"name": "B", "lat": 40.0, "lon": -98.0},
        "departure": departure,
        "load_lb": 35_000,
        "interval_mi": 10,
    }
    body.update(overrides)
    return body


def _post(body):
    return Client().post("/api/plan", data=json.dumps(body), content_type="application/json")


def test_plan_recommends_the_calm_route_over_the_fast_windy_one(stub_providers):
    res = _post(_body())
    assert res.status_code == 200
    data = res.json()
    best = next(r for r in data["routes"] if r["id"] == data["recommended_route_id"])
    assert best["name"] == "Slow calm"
    windy = next(r for r in data["routes"] if r["name"] == "Fast windy")
    # 50 mph with a 35,000 lb load is No Travel under the load rules.
    assert windy["summary"]["no_travel_miles"] > 0
    assert "No Travel" in data["recommendation_reason"]
    cp = windy["checkpoints"][0]
    assert {"mile", "lat", "lon", "eta", "risk", "risk_label", "weather"} <= cp.keys()


def test_heatmap_is_available_for_a_plan(stub_providers):
    plan_id = _post(_body()).json()["plan_id"]
    res = Client().get(f"/api/plans/{plan_id}/heatmap")
    assert res.status_code == 200
    data = res.json()
    assert len(data["hours"]) == 49
    assert all(len(p["risk"]) == 49 for p in data["points"])


def test_heatmap_unknown_plan_is_404():
    assert Client().get("/api/plans/nope/heatmap").status_code == 404


@pytest.mark.parametrize(
    "overrides,message",
    [
        ({"interval_mi": 15}, "10, 25 or 50"),
        ({"load_lb": -1}, "Load weight"),
        ({"load_lb": "heavy"}, "Load weight"),
        ({"departure": "tomorrow"}, "ISO 8601"),
        ({"departure": "2020-01-01T00:00:00+00:00"}, "past"),
        ({"departure": "2030-01-01T00:00"}, "timezone"),
        ({"origin": None}, "Origin is required"),
        ({"destination": {"lat": 40.0, "lon": -100.0}}, "same place"),
    ],
)
def test_plan_validation(overrides, message):
    res = _post(_body(**overrides))
    assert res.status_code == 400
    assert message in res.json()["error"]


def test_reverse_geocode_labels_by_street_and_city(monkeypatch):
    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            props = {"name": "The Fat Shallot", "street": "West Adams Street", "city": "Chicago", "state": "Illinois"}
            return {"features": [{"properties": props}]}

    monkeypatch.setattr(providers._session, "get", lambda *a, **k: Resp())
    res = Client().get("/api/reverse-geocode", {"lat": 41.8794, "lon": -87.6306})
    assert res.status_code == 200
    assert res.json() == {
        "name": "Current location: West Adams Street, Chicago, Illinois",
        "lat": 41.8794,
        "lon": -87.6306,
    }


def test_reverse_geocode_falls_back_to_coordinates(monkeypatch):
    def boom(*a, **k):
        raise providers.requests.ConnectionError("down")

    monkeypatch.setattr(providers._session, "get", boom)
    res = Client().get("/api/reverse-geocode", {"lat": 10, "lon": 20})
    assert res.json()["name"] == "Current location (10.0000, 20.0000)"


def test_reverse_geocode_validates_input():
    assert Client().get("/api/reverse-geocode", {"lat": "x", "lon": 1}).status_code == 400
    assert Client().get("/api/reverse-geocode", {"lat": 95, "lon": 1}).status_code == 400

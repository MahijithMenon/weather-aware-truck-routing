"""JSON API: /api/geocode, /api/plan, /api/plans/<id>/heatmap."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .services import planner, providers
from .services.geo import haversine_mi

log = logging.getLogger(__name__)

ALLOWED_INTERVALS = (10, 25, 50)
MAX_LOAD_LB = 120_000  # well above the 80,000 lb US federal gross limit; catches typos
MAX_DAYS_AHEAD = 7  # the forecast must cover the whole trip plus the 48 h heatmap


def _error(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"error": message}, status=status)


@require_GET
def geocode(request: HttpRequest) -> JsonResponse:
    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return JsonResponse({"results": []})
    try:
        places = providers.geocode(q)
    except providers.ProviderError as exc:
        return _error(str(exc), 502)
    return JsonResponse({"results": [vars(p) for p in places]})


@require_GET
def reverse_geocode(request: HttpRequest) -> JsonResponse:
    try:
        lat, lon = float(request.GET["lat"]), float(request.GET["lon"])
    except (KeyError, ValueError):
        return _error("lat and lon are required numbers")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return _error("Coordinates out of range")
    return JsonResponse(vars(providers.reverse_geocode(lat, lon)))


def _parse_place(value, field: str) -> providers.Place:
    """Accept {name, lat, lon} from the autocomplete, or plain text to geocode."""
    if isinstance(value, dict) and "lat" in value and "lon" in value:
        try:
            lat, lon = float(value["lat"]), float(value["lon"])
        except (TypeError, ValueError):
            raise ValueError(f"{field}: invalid coordinates")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError(f"{field}: coordinates out of range")
        return providers.Place(str(value.get("name") or f"{lat:.4f}, {lon:.4f}"), lat, lon)
    if isinstance(value, str) and value.strip():
        matches = providers.geocode(value.strip(), limit=1)
        if not matches:
            raise ValueError(f"{field}: couldn't find '{value}'")
        return matches[0]
    raise ValueError(f"{field} is required")


def _parse_trip(body: dict) -> planner.TripRequest:
    origin = _parse_place(body.get("origin"), "Origin")
    dest = _parse_place(body.get("destination"), "Destination")

    raw_departure = body.get("departure")
    try:
        departure = datetime.fromisoformat(str(raw_departure).replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Departure must be an ISO 8601 date/time")
    if departure.tzinfo is None:
        raise ValueError("Departure must include a timezone offset")
    departure = departure.astimezone(timezone.utc)
    now = datetime.now(timezone.utc)
    if departure < now - timedelta(hours=1):
        raise ValueError("Departure can't be in the past")
    if departure > now + timedelta(days=MAX_DAYS_AHEAD):
        raise ValueError(f"Departure must be within {MAX_DAYS_AHEAD} days (forecast range)")

    try:
        load_lb = float(body.get("load_lb"))
    except (TypeError, ValueError):
        raise ValueError("Load weight must be a number of pounds")
    if not (0 <= load_lb <= MAX_LOAD_LB):
        raise ValueError(f"Load weight must be between 0 and {MAX_LOAD_LB:,} lb")

    try:
        interval = int(body.get("interval_mi", 25))
    except (TypeError, ValueError):
        interval = -1
    if interval not in ALLOWED_INTERVALS:
        raise ValueError("Checkpoint interval must be 10, 25 or 50 miles")

    if haversine_mi((origin.lat, origin.lon), (dest.lat, dest.lon)) < 1:
        raise ValueError("Origin and destination are the same place")
    return planner.TripRequest(origin, dest, departure, load_lb, interval)


@csrf_exempt  # stateless JSON API with no cookies/sessions
@require_POST
def plan(request: HttpRequest) -> JsonResponse:
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return _error("Request body must be JSON")
    if not isinstance(body, dict):
        return _error("Request body must be a JSON object")
    try:
        trip = _parse_trip(body)
        return JsonResponse(planner.plan_trip(trip))
    except ValueError as exc:
        return _error(str(exc))
    except planner.PlanningError as exc:
        return _error(str(exc), 422)
    except providers.ProviderError as exc:
        log.warning("provider failure: %s", exc)
        return _error(str(exc), 502)


@require_GET
def plan_heatmap(request: HttpRequest, plan_id: str) -> JsonResponse:
    try:
        return JsonResponse(planner.heatmap(plan_id))
    except planner.PlanningError as exc:
        return _error(str(exc), 404)
    except providers.ProviderError as exc:
        log.warning("provider failure: %s", exc)
        return _error(str(exc), 502)

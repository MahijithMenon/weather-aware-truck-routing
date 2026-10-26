# Weather-Aware Truck Routing

A Next.js + Django app that helps a truck driver pick the safest route. It compares three route options using the
forecast at each checkpoint for the time the truck will actually be there. Each route is scored with the
assessment's wind/rain/snow and load rules, and the best one is recommended.

![stack](https://img.shields.io/badge/frontend-Next.js%2015%20%2B%20Leaflet-black) ![stack](https://img.shields.io/badge/backend-Django%205.2-0c4b33)

## What it does

1. **Input:** origin and destination (with autocomplete), departure date/time, load weight, and a checkpoint interval of 10, 25 or 50 mi. The origin can be your **current location**: the crosshair button uses the browser's geolocation, with the coordinates labelled by reverse geocoding. A typed place that wasn't picked from the suggestions is geocoded by the API.
2. **Routes:** fetches up to 3 distinct route options (see [Routing](#routing)).
3. **Checkpoints:** places a checkpoint every N miles, plus one at the destination, and computes the truck's ETA at each one.
4. **Weather:** gets the hourly forecast at each checkpoint, interpolated to that checkpoint's ETA.
5. **Risk:** classifies each checkpoint with the risk table and load rules.
6. **Recommendation:** ranks routes by fewest Severe miles, then fewest High miles, then lowest average risk, then shortest time, and explains which criterion decided it.
7. **Map:** shows every route and its checkpoints. The selected route is colored by risk, and each checkpoint popup lists the ETA, weather values, per-condition risk, and the reason for its level.
8. **Heatmap:** shows a weather heatmap along the trip corridor with a 0–48 h slider (hours after departure), a play button, and Risk / Wind / Rain / Snow layers. A truck marker shows where the truck is on the selected route at the slider time.

## Architecture

```
frontend/  Next.js 15 (App Router, TypeScript), react-leaflet, custom canvas heat layer
  └─ /api/* is proxied to Django (next.config.ts rewrites), so the browser needs no CORS
backend/   Django 5.2 JSON API, no database
  routing/services/
    risk.py       risk table, load rules, route summary + ranking (pure functions, fully unit tested)
    geo.py        polyline decoding, haversine, interpolation by mile/time
    providers.py  OSRM (routing), Open-Meteo (weather), Photon (geocoding) clients, plus caching
    planner.py    orchestration: routes → checkpoints → forecasts → risk → ranking; heatmap corridor
  routing/views.py  validation and HTTP endpoints
```

| Endpoint | Purpose |
|---|---|
| `GET /api/geocode?q=` | Place autocomplete (Photon / OpenStreetMap) |
| `GET /api/reverse-geocode?lat=&lon=` | Label for the user's current location (street, city, state); keeps the exact coordinates |
| `POST /api/plan` | `{origin, destination, departure, load_lb, interval_mi}` → routes, checkpoints, summaries, recommendation, `plan_id` |
| `GET /api/plans/<plan_id>/heatmap` | 49 hourly frames of risk, wind, rain and snow for points covering the corridor |

All third-party services are free and need no API keys.

## Risk logic

The rules are in [`backend/routing/services/risk.py`](backend/routing/services/risk.py) and tested in
[`test_risk.py`](backend/routing/tests/test_risk.py).

| Condition | Low | Moderate | High | Severe | No Travel |
|---|---|---|---|---|---|
| Wind (sustained, mph) | <25 | 25–34 | 35–44 | 45–54 | ≥55 |
| Rain (in/hr) | <0.10 | 0.10–0.25 | 0.25–0.50 | 0.50–1.00 | >1.00 |
| Snow (in/hr) | <0.5 | 0.5–1.0 | 1.0–2.0 | 2.0–3.0 | >3.0 |

Load rules apply to the wind band: 45–54 mph with more than 30,000 lb is **No Travel**, and 35–44 mph with more
than 40,000 lb is **Severe**.

### Interpretations (where the spec is ambiguous)

- **Shared band edges** (e.g. rain 0.25 sits in both 0.10–0.25 and 0.25–0.50): the lower bound is inclusive, so the value goes to the **higher** band, the conservative choice. The No Travel rows for rain and snow say `>`, so exactly 1.00 in/hr rain or 3.0 in/hr snow stays Severe.
- **Load thresholds** are strict (`> 30,000`, `> 40,000`), as written.
- **Checkpoint risk** is the worst of wind (after load rules), rain and snow.
- **Miles per risk level:** each checkpoint covers the road halfway to its neighbours. With 25-mile spacing, each checkpoint counts for the 12.5 mi on either side of it.
- **Severe miles** include No Travel miles, since No Travel is strictly worse. On top of the four specified criteria, routes with fewer **No Travel** miles rank first, so a slightly shorter route with an impassable stretch never wins. If every route has No Travel conditions, the UI shows a warning.
- **Average risk** is distance-weighted on a 0 (Low) to 4 (No Travel) scale.
- Mileage is rounded to 0.1 mi and average risk to 0.01 when ranking, so floating-point noise between near-identical routes can't decide the result.
- **Rain** is Open-Meteo `rain + showers` (liquid, inches in the hour). **Snow** is `snowfall` (inches of snow in the hour). **Wind** is sustained 10 m wind; gusts are shown in popups but not scored.

## Routing

- OSRM's public server provides the routes. It only has a car profile, so every segment is capped at **65 mph** to approximate truck travel time, and ETAs use that adjusted time.
- The public server returns at most 2 alternatives. To always offer 3 distinct options, the planner also routes through via points offset to either side of the straight origin–destination line, all requested in parallel. Candidates are kept only if they are distinct (under 90% overlap with an already chosen route) and practical (at most 1.5× the fastest route's distance and time). Some trips have only two sensible corridors, and the UI says so.
- ETA at each checkpoint comes from OSRM's per-segment duration annotations, with weather linearly interpolated between forecast hours.

## Heatmap performance

The heatmap needs to stay smooth while scrubbing, so:

- The backend samples a corridor band of points along and either side of every route (about 300 points), fetches all 49 hours in one batched Open-Meteo pass, and returns compact arrays (about 20 KB gzipped). Scrubbing the slider never goes back to the network.
- [`RiskHeatLayer`](frontend/src/components/map/RiskHeatLayer.ts) is a custom Leaflet canvas layer. Points are projected and bucketed only on pan/zoom. Each hour change recomputes an inverse-distance-weighted field on a quarter-resolution grid and upscales it with smoothing, taking about one animation frame. Pixels are colored by the **same risk bands** as the rules, so the heatmap's boundaries match the classification thresholds. Raw wind/rain/snow layers map onto the same scale using the table's thresholds.
- Maps use the canvas renderer (`preferCanvas`), route components are memoized, and the heatmap loads after the routes so the routes appear first.
- Routes, forecasts and geocoding results are cached in memory (forecasts for 30 min, rounded to a ~3 mi grid), so overlapping routes and the heatmap share forecast lookups.

## Running locally

Requirements: Python 3.12+, Node 20+.

```bash
# Backend (http://localhost:8000)
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py runserver 8000
```

```bash
# Frontend (http://localhost:3000), proxies /api to the backend
cd frontend
npm install
npm run dev
```

Tests:

```bash
cd backend && .venv/bin/pytest -q
```

## Deployment

- **Backend → Render:** `render.yaml` is a ready blueprint (a `backend/Dockerfile` is included too). It runs one gunicorn process with threads, because plans and forecasts live in an in-process cache. For multiple instances, swap `CACHES` for Redis.
- **Frontend → Vercel:** set the root directory to `frontend` and set `BACKEND_URL` to the Render service URL.

Optional backend environment variables: `OSRM_URL`, `OPEN_METEO_URL`, `PHOTON_URL` (to point at self-hosted
instances), plus `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`.

## Limitations

- OSRM's car profile doesn't know truck restrictions (bridge heights, hazmat, weight limits). A production version would use a truck-aware router such as HERE, ORS `driving-hgv`, or GraphHopper truck.
- The forecast horizon limits departures to the next 7 days.
- Browsers only share location over https or on localhost. If permission is denied, the app explains why and you can type a place instead.
- The public OSRM demo server is rate-limited and its latency varies, so a cold plan can take 5–20 s. The client retries once on timeout.

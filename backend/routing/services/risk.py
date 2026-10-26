"""Weather risk classification and route ranking.

Pure functions with no I/O, so the assessment rules can be unit tested directly.

Threshold convention: each band's lower bound is inclusive, so a value sitting on
a shared boundary (e.g. rain of exactly 0.25 in/hr) goes to the higher band.
The "No Travel" rain/snow rows say "> x", so the boundary value itself (1.00 in/hr
rain, 3.0 in/hr snow) stays Severe.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Risk(IntEnum):
    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4

    @property
    def label(self) -> str:
        return RISK_LABELS[self]


RISK_LABELS = {
    Risk.LOW: "Low",
    Risk.MODERATE: "Moderate",
    Risk.HIGH: "High",
    Risk.SEVERE: "Severe",
    Risk.NO_TRAVEL: "No Travel",
}


def classify_wind(mph: float) -> Risk:
    if mph >= 55:
        return Risk.NO_TRAVEL
    if mph >= 45:
        return Risk.SEVERE
    if mph >= 35:
        return Risk.HIGH
    if mph >= 25:
        return Risk.MODERATE
    return Risk.LOW


def classify_rain(in_per_hr: float) -> Risk:
    if in_per_hr > 1.00:
        return Risk.NO_TRAVEL
    if in_per_hr >= 0.50:
        return Risk.SEVERE
    if in_per_hr >= 0.25:
        return Risk.HIGH
    if in_per_hr >= 0.10:
        return Risk.MODERATE
    return Risk.LOW


def classify_snow(in_per_hr: float) -> Risk:
    if in_per_hr > 3.0:
        return Risk.NO_TRAVEL
    if in_per_hr >= 2.0:
        return Risk.SEVERE
    if in_per_hr >= 1.0:
        return Risk.HIGH
    if in_per_hr >= 0.5:
        return Risk.MODERATE
    return Risk.LOW


def apply_load_rules(wind_mph: float, load_lb: float) -> Risk:
    """Wind risk adjusted for the truck's load.

    - >= 55 mph: No Travel for any load (already covered by classify_wind)
    - 45-54 mph and > 30,000 lb: No Travel
    - 35-44 mph and > 40,000 lb: Severe
    """
    base = classify_wind(wind_mph)
    if base == Risk.SEVERE and load_lb > 30_000:
        return Risk.NO_TRAVEL
    if base == Risk.HIGH and load_lb > 40_000:
        return Risk.SEVERE
    return base


@dataclass(frozen=True)
class Assessment:
    risk: Risk
    wind_risk: Risk
    rain_risk: Risk
    snow_risk: Risk
    reasons: tuple[str, ...]


def assess(wind_mph: float, rain_in_hr: float, snow_in_hr: float, load_lb: float) -> Assessment:
    """Overall checkpoint risk is the worst of wind (load-adjusted), rain and snow."""
    wind_risk = apply_load_rules(wind_mph, load_lb)
    rain_risk = classify_rain(rain_in_hr)
    snow_risk = classify_snow(snow_in_hr)
    risk = max(wind_risk, rain_risk, snow_risk)

    reasons: list[str] = []
    if risk > Risk.LOW:
        if wind_risk == risk:
            note = f"Wind {wind_mph:.0f} mph"
            if wind_risk != classify_wind(wind_mph):
                note += f" with {load_lb:,.0f} lb load"
            reasons.append(note)
        if rain_risk == risk:
            reasons.append(f"Rain {rain_in_hr:.2f} in/hr")
        if snow_risk == risk:
            reasons.append(f"Snow {snow_in_hr:.2f} in/hr")
    return Assessment(risk, wind_risk, rain_risk, snow_risk, tuple(reasons))


@dataclass(frozen=True)
class RouteRiskSummary:
    total_miles: float
    duration_s: float
    miles_by_risk: dict[Risk, float]
    average_risk: float

    @property
    def severe_miles(self) -> float:
        """Severe-or-worse miles. No Travel miles are strictly worse than Severe,
        so they count here as well as being ranked first in `ranking_key`."""
        return self.miles_by_risk[Risk.SEVERE] + self.miles_by_risk[Risk.NO_TRAVEL]

    @property
    def high_miles(self) -> float:
        return self.miles_by_risk[Risk.HIGH]

    @property
    def no_travel_miles(self) -> float:
        return self.miles_by_risk[Risk.NO_TRAVEL]


def summarize_segments(segments: list[tuple[float, Risk]], duration_s: float) -> RouteRiskSummary:
    """Summarize a route from (miles, risk) segments.

    Average risk is distance weighted, on the 0 (Low) to 4 (No Travel) scale.
    """
    miles_by_risk = {r: 0.0 for r in Risk}
    total = 0.0
    weighted = 0.0
    for miles, risk in segments:
        miles_by_risk[risk] += miles
        total += miles
        weighted += miles * int(risk)
    return RouteRiskSummary(
        total_miles=total,
        duration_s=duration_s,
        miles_by_risk=miles_by_risk,
        average_risk=weighted / total if total else 0.0,
    )


def ranking_key(summary: RouteRiskSummary) -> tuple:
    """Sort key implementing the assessment's preference order.

    0. Fewest No Travel miles (a route you legally/safely can't drive loses first)
    1. Fewest Severe miles
    2. Fewest High miles
    3. Lowest average risk
    4. Shortest travel time

    Mileage is rounded to 0.1 mi and average risk to 0.01 so floating point
    noise between near-identical routes doesn't decide the outcome.
    """
    return (
        round(summary.no_travel_miles, 1),
        round(summary.severe_miles, 1),
        round(summary.high_miles, 1),
        round(summary.average_risk, 2),
        summary.duration_s,
    )


def explain_choice(best: RouteRiskSummary, runner_up: RouteRiskSummary | None) -> str:
    """Name the criterion that separated the winner from the runner-up."""
    if runner_up is None:
        return "Only one route was available."
    b, r = ranking_key(best), ranking_key(runner_up)
    criteria = [
        ("fewer No Travel miles", lambda s: f"{s.no_travel_miles:.0f} mi"),
        ("fewer Severe miles", lambda s: f"{s.severe_miles:.0f} mi"),
        ("fewer High risk miles", lambda s: f"{s.high_miles:.0f} mi"),
        ("lower average risk", lambda s: f"{s.average_risk:.2f}"),
        ("shorter travel time", lambda s: f"{s.duration_s / 3600:.1f} h"),
    ]
    for i, (text, fmt) in enumerate(criteria):
        if b[i] != r[i]:
            return f"Recommended for {text} ({fmt(best)} vs {fmt(runner_up)} on the next best route)."
    return "Routes are equivalent on every criterion; picked the first."

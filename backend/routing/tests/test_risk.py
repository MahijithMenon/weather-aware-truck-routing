import pytest

from routing.services.risk import (
    Risk,
    apply_load_rules,
    assess,
    classify_rain,
    classify_snow,
    classify_wind,
    explain_choice,
    ranking_key,
    summarize_segments,
)


@pytest.mark.parametrize(
    "mph,expected",
    [
        (0, Risk.LOW),
        (24.9, Risk.LOW),
        (25, Risk.MODERATE),
        (34.9, Risk.MODERATE),
        (35, Risk.HIGH),
        (44.9, Risk.HIGH),
        (45, Risk.SEVERE),
        (54.9, Risk.SEVERE),
        (55, Risk.NO_TRAVEL),
        (80, Risk.NO_TRAVEL),
    ],
)
def test_wind_thresholds(mph, expected):
    assert classify_wind(mph) == expected


@pytest.mark.parametrize(
    "rate,expected",
    [
        (0.0, Risk.LOW),
        (0.09, Risk.LOW),
        (0.10, Risk.MODERATE),
        (0.25, Risk.HIGH),  # shared boundary goes to the higher band
        (0.49, Risk.HIGH),
        (0.50, Risk.SEVERE),
        (1.00, Risk.SEVERE),  # "> 1.00" is No Travel, so 1.00 itself is Severe
        (1.01, Risk.NO_TRAVEL),
    ],
)
def test_rain_thresholds(rate, expected):
    assert classify_rain(rate) == expected


@pytest.mark.parametrize(
    "rate,expected",
    [
        (0.0, Risk.LOW),
        (0.49, Risk.LOW),
        (0.5, Risk.MODERATE),
        (1.0, Risk.HIGH),
        (2.0, Risk.SEVERE),
        (3.0, Risk.SEVERE),
        (3.01, Risk.NO_TRAVEL),
    ],
)
def test_snow_thresholds(rate, expected):
    assert classify_snow(rate) == expected


@pytest.mark.parametrize(
    "mph,load,expected",
    [
        (60, 0, Risk.NO_TRAVEL),  # >= 55 mph: No Travel for any load
        (55, 10_000, Risk.NO_TRAVEL),
        (50, 30_000, Risk.SEVERE),  # 45-54 needs strictly > 30,000 lb
        (50, 30_001, Risk.NO_TRAVEL),
        (45, 45_000, Risk.NO_TRAVEL),
        (40, 40_000, Risk.HIGH),  # 35-44 needs strictly > 40,000 lb
        (40, 40_001, Risk.SEVERE),
        (35, 80_000, Risk.SEVERE),
        (30, 80_000, Risk.MODERATE),  # load rules don't touch lower wind bands
    ],
)
def test_load_rules(mph, load, expected):
    assert apply_load_rules(mph, load) == expected


def test_assess_takes_worst_condition_and_explains_it():
    a = assess(wind_mph=10, rain_in_hr=0.3, snow_in_hr=0.6, load_lb=20_000)
    assert a.risk == Risk.HIGH
    assert a.reasons == ("Rain 0.30 in/hr",)


def test_assess_mentions_load_when_it_raised_the_risk():
    a = assess(wind_mph=40, rain_in_hr=0, snow_in_hr=0, load_lb=42_000)
    assert a.risk == Risk.SEVERE
    assert "42,000 lb" in a.reasons[0]


def test_assess_low_has_no_reasons():
    assert assess(5, 0, 0, 10_000).reasons == ()


def _summary(segments, hours):
    return summarize_segments(segments, hours * 3600)


def test_summary_average_is_distance_weighted():
    s = _summary([(30, Risk.LOW), (10, Risk.SEVERE)], 1)
    assert s.total_miles == 40
    assert s.average_risk == pytest.approx(0.75)
    assert s.severe_miles == 10


def test_ranking_prefers_fewest_severe_then_high_then_avg_then_time():
    fast_but_severe = _summary([(90, Risk.LOW), (10, Risk.SEVERE)], 5)
    slow_but_high = _summary([(100, Risk.LOW), (50, Risk.HIGH)], 9)
    slow_clean = _summary([(200, Risk.LOW)], 12)
    ordered = sorted([fast_but_severe, slow_but_high, slow_clean], key=ranking_key)
    assert ordered == [slow_clean, slow_but_high, fast_but_severe]


def test_ranking_average_risk_breaks_ties_before_time():
    calm = _summary([(100, Risk.LOW)], 3)
    breezy_faster = _summary([(100, Risk.MODERATE)], 2)
    assert sorted([breezy_faster, calm], key=ranking_key)[0] is calm


def test_ranking_falls_back_to_travel_time():
    a = _summary([(100, Risk.LOW)], 3)
    b = _summary([(110, Risk.LOW)], 2.5)
    assert sorted([a, b], key=ranking_key)[0] is b


def test_no_travel_ranks_below_severe():
    blocked = _summary([(95, Risk.LOW), (5, Risk.NO_TRAVEL)], 2)
    severe = _summary([(90, Risk.LOW), (10, Risk.SEVERE)], 2)
    assert sorted([blocked, severe], key=ranking_key)[0] is severe


def test_explain_choice_names_deciding_criterion():
    a = _summary([(100, Risk.LOW)], 3)
    b = _summary([(80, Risk.LOW), (20, Risk.HIGH)], 2)
    assert "fewer High risk miles" in explain_choice(a, b)
    assert explain_choice(a, None) == "Only one route was available."

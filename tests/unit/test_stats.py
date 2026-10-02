from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.services.prices import expected_point_count, summarize_prices
from app.sources.base import dutch_day_window

DAY = date(2026, 10, 1)


@pytest.mark.parametrize(
    ("day", "expected"),
    [(date(2026, 10, 1), 24), (date(2025, 10, 26), 25), (date(2026, 3, 29), 23)],
    ids=["normal", "dst-end", "dst-start"],
)
def test_expected_point_count(day, expected):
    assert expected_point_count(day) == expected


def test_complete_day(make_points):
    prices = ["0.2"] * 24
    prices[3], prices[19] = "0.05", "0.40"
    points = make_points(DAY, prices)

    stats = summarize_prices(points, expected_point_count(DAY))

    start = dutch_day_window(DAY)[0]
    assert (stats.count, stats.expected_count, stats.is_complete) == (24, 24, True)
    assert (stats.min_price, stats.min_price_start) == (Decimal("0.05"), start + timedelta(hours=3))
    assert (stats.max_price, stats.max_price_start) == (
        Decimal("0.40"),
        start + timedelta(hours=19),
    )
    assert stats.average_price == Decimal("0.2020833333")  # (22*0.2 + 0.05 + 0.40) / 24 = 4.85 / 24


def test_incomplete_day(make_points):
    points = make_points(DAY, ["0.2"] * 24, skip={5})

    stats = summarize_prices(points, expected_point_count(DAY))

    assert (stats.count, stats.expected_count, stats.is_complete) == (23, 24, False)


def test_tied_extremes_report_earliest_hour(make_points):
    points = make_points(DAY, ["0.1", "0.3", "0.1", "0.3"])

    stats = summarize_prices(points, 24)

    assert stats.min_price_start == points[0].start_utc
    assert stats.max_price_start == points[1].start_utc


@pytest.mark.parametrize(("day", "hours"), [(date(2025, 10, 26), 25), (date(2026, 3, 29), 23)])
def test_dst_days_are_complete_with_their_own_hour_count(make_points, day, hours):
    points = make_points(day, ["0.1"] * hours)

    stats = summarize_prices(points, expected_point_count(day))

    assert (stats.count, stats.expected_count, stats.is_complete) == (hours, hours, True)


def test_empty_points_raise():
    with pytest.raises(ValueError):
        summarize_prices([], 24)

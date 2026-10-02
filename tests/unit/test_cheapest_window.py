from datetime import date, timedelta
from decimal import Decimal

from app.services.prices import find_cheapest_window
from app.sources.base import dutch_day_window

DAY = date(2026, 10, 1)
MIDNIGHT_UTC = dutch_day_window(DAY)[0]


def hour(i: int):
    return MIDNIGHT_UTC + timedelta(hours=i)


def test_finds_cheapest_block(make_points):
    points = make_points(DAY, ["5", "4", "1", "2", "3", "6"])

    window = find_cheapest_window(points, hours=2)

    assert (window.start, window.end) == (hour(2), hour(4))
    assert window.average_price == Decimal("1.5000000000")
    assert [p.price_eur_per_kwh for p in window.points] == [Decimal(1), Decimal(2)]


def test_never_spans_a_gap(make_points):
    # Hour 2 is missing. Hours 1 and 3 (price 1 + 1) look cheapest but are not consecutive.
    points = make_points(DAY, ["9", "1", "0", "1", "8", "9"], skip={2})

    window = find_cheapest_window(points, hours=2)

    assert (window.start, window.end) == (hour(3), hour(5))
    assert window.average_price == Decimal("4.5000000000")


def test_ties_resolve_to_earliest_window(make_points):
    points = make_points(DAY, ["3", "1", "1", "3", "1", "1"])

    window = find_cheapest_window(points, hours=2)

    assert window.start == hour(1)


def test_handles_negative_prices(make_points):
    points = make_points(DAY, ["0.10", "-0.05", "-0.02", "0.20"])

    window = find_cheapest_window(points, hours=2)

    assert window.start == hour(1)
    assert window.average_price == Decimal("-0.0350000000")


def test_returns_none_when_window_is_longer_than_longest_run(make_points):
    points = make_points(DAY, ["1", "2", "0", "3", "4"], skip={2})

    assert find_cheapest_window(points, hours=3) is None
    assert find_cheapest_window(points, hours=2) is not None


def test_window_may_equal_whole_run(make_points):
    points = make_points(DAY, ["1", "2", "3"])

    window = find_cheapest_window(points, hours=3)

    assert (window.start, window.end) == (hour(0), hour(3))


def test_spans_dst_clock_change_because_hours_are_consecutive_in_utc(make_points):
    # 2025-10-26: index 2 and 3 are both "02:00" local (+02:00 then +01:00), one hour apart in UTC.
    prices = ["9"] * 25
    prices[2], prices[3] = "1", "1"
    points = make_points(date(2025, 10, 26), prices)

    window = find_cheapest_window(points, hours=2)

    assert window.points == points[2:4]
    assert window.end - window.start == timedelta(hours=2)

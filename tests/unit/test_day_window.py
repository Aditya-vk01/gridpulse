from datetime import UTC, date, datetime

import pytest

from app.sources.base import dutch_day_window


@pytest.mark.parametrize(
    ("day", "expected_start", "expected_end", "hours"),
    [
        pytest.param(
            date(2026, 10, 1),
            datetime(2026, 9, 30, 22, tzinfo=UTC),
            datetime(2026, 10, 1, 22, tzinfo=UTC),
            24,
            id="summer-time-24h",
        ),
        pytest.param(
            date(2025, 10, 26),
            datetime(2025, 10, 25, 22, tzinfo=UTC),
            datetime(2025, 10, 26, 23, tzinfo=UTC),
            25,
            id="dst-end-25h",
        ),
        pytest.param(
            date(2026, 3, 29),
            datetime(2026, 3, 28, 23, tzinfo=UTC),
            datetime(2026, 3, 29, 22, tzinfo=UTC),
            23,
            id="dst-start-23h",
        ),
    ],
)
def test_dutch_day_window(day, expected_start, expected_end, hours):
    start, end = dutch_day_window(day)

    assert (start, end) == (expected_start, expected_end)
    assert start.utcoffset().total_seconds() == 0
    assert (end - start).total_seconds() == hours * 3600

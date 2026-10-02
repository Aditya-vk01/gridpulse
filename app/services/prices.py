"""Read-only price queries. Nothing here fetches from a source or writes to the database."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PricePoint
from app.sources.base import dutch_day_window

DEFAULT_SOURCE = "energyzero"
HOURLY = 60
PRICE_QUANTUM = Decimal("1E-10")  # same scale as price_points.price_eur_per_kwh


class NoPriceDataError(Exception):
    def __init__(self, day: date, source: str) -> None:
        super().__init__(f"No price data for {day.isoformat()} (source: {source})")


class InsufficientDataError(Exception):
    pass


@dataclass(frozen=True)
class DailyStats:
    count: int
    expected_count: int
    is_complete: bool
    min_price: Decimal
    min_price_start: datetime
    max_price: Decimal
    max_price_start: datetime
    average_price: Decimal


@dataclass(frozen=True)
class CheapestWindow:
    start: datetime
    end: datetime
    average_price: Decimal
    points: list[PricePoint]


def _average(values: list[Decimal]) -> Decimal:
    return (sum(values, Decimal(0)) / len(values)).quantize(PRICE_QUANTUM, ROUND_HALF_EVEN)


def get_prices(session: Session, day: date, source: str = DEFAULT_SOURCE) -> list[PricePoint]:
    start_utc, end_utc = dutch_day_window(day)
    stmt = (
        select(PricePoint)
        .where(
            PricePoint.source == source,
            PricePoint.resolution_minutes == HOURLY,
            PricePoint.start_utc >= start_utc,
            PricePoint.start_utc < end_utc,
        )
        .order_by(PricePoint.start_utc)
    )
    return list(session.scalars(stmt))


def get_daily_stats(session: Session, day: date, source: str = DEFAULT_SOURCE) -> DailyStats:
    points = get_prices(session, day, source)
    if not points:
        raise NoPriceDataError(day, source)

    start_utc, end_utc = dutch_day_window(day)
    expected = int((end_utc - start_utc) / timedelta(minutes=HOURLY))
    # min()/max() return the first match, so ties resolve to the earliest hour.
    cheapest = min(points, key=lambda p: p.price_eur_per_kwh)
    priciest = max(points, key=lambda p: p.price_eur_per_kwh)
    return DailyStats(
        count=len(points),
        expected_count=expected,
        is_complete=len(points) == expected,
        min_price=cheapest.price_eur_per_kwh,
        min_price_start=cheapest.start_utc,
        max_price=priciest.price_eur_per_kwh,
        max_price_start=priciest.start_utc,
        average_price=_average([p.price_eur_per_kwh for p in points]),
    )


def get_cheapest_window(
    session: Session, day: date, hours: int, source: str = DEFAULT_SOURCE
) -> CheapestWindow:
    """Find the N consecutive hours with the lowest average price; earliest wins on ties.

    Windows never span a gap in the data: the running sum restarts whenever two
    neighbouring points are not exactly one hour apart in UTC.
    """
    points = get_prices(session, day, source)
    if not points:
        raise NoPriceDataError(day, source)

    step = timedelta(minutes=HOURLY)
    best_start: int | None = None
    best_sum = Decimal(0)
    run_start = 0
    longest_run = 0
    window_sum = Decimal(0)
    for i, point in enumerate(points):
        if i > 0 and point.start_utc - points[i - 1].start_utc != step:
            run_start = i
            window_sum = Decimal(0)
        window_sum += point.price_eur_per_kwh
        run_length = i - run_start + 1
        longest_run = max(longest_run, run_length)
        if run_length > hours:
            window_sum -= points[i - hours].price_eur_per_kwh
        if run_length >= hours and (best_start is None or window_sum < best_sum):
            best_start, best_sum = i - hours + 1, window_sum

    if best_start is None:
        raise InsufficientDataError(
            f"Requested {hours} consecutive hours, but the longest run of consecutive "
            f"price data for {day.isoformat()} is {longest_run} hours"
        )
    window = points[best_start : best_start + hours]
    return CheapestWindow(
        start=window[0].start_utc,
        end=window[-1].start_utc + step,
        average_price=_average([p.price_eur_per_kwh for p in window]),
        points=window,
    )

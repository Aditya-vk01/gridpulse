"""Read-only price queries. Nothing here fetches from a source or writes to the database."""

from collections.abc import Sequence
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


def expected_point_count(day: date, resolution_minutes: int = HOURLY) -> int:
    """Number of points in a complete Dutch day: 23, 24 or 25 for hourly data."""
    start_utc, end_utc = dutch_day_window(day)
    return int((end_utc - start_utc) / timedelta(minutes=resolution_minutes))


def summarize_prices(points: Sequence[PricePoint], expected_count: int) -> DailyStats:
    """Pure statistics over a non-empty, time-ordered list of points."""
    if not points:
        raise ValueError("points must not be empty")
    # min()/max() return the first match, so ties resolve to the earliest hour.
    cheapest = min(points, key=lambda p: p.price_eur_per_kwh)
    priciest = max(points, key=lambda p: p.price_eur_per_kwh)
    return DailyStats(
        count=len(points),
        expected_count=expected_count,
        is_complete=len(points) == expected_count,
        min_price=cheapest.price_eur_per_kwh,
        min_price_start=cheapest.start_utc,
        max_price=priciest.price_eur_per_kwh,
        max_price_start=priciest.start_utc,
        average_price=_average([p.price_eur_per_kwh for p in points]),
    )


def split_into_runs(points: Sequence[PricePoint]) -> list[list[PricePoint]]:
    """Split time-ordered points into runs where each point starts exactly one hour
    after the previous one in UTC. A missing hour starts a new run."""
    step = timedelta(minutes=HOURLY)
    runs: list[list[PricePoint]] = []
    for point in points:
        if runs and point.start_utc - runs[-1][-1].start_utc == step:
            runs[-1].append(point)
        else:
            runs.append([point])
    return runs


def find_cheapest_window(points: Sequence[PricePoint], hours: int) -> CheapestWindow | None:
    """Pure sliding-window search for the N consecutive hours with the lowest average
    price. Windows never span a gap in the data; the earliest window wins on ties.
    Returns None if no run of consecutive data is at least `hours` long."""
    best: list[PricePoint] | None = None
    best_sum = Decimal(0)
    for run in split_into_runs(points):
        window_sum = Decimal(0)
        for i, point in enumerate(run):
            window_sum += point.price_eur_per_kwh
            if i >= hours:
                window_sum -= run[i - hours].price_eur_per_kwh
            if i >= hours - 1 and (best is None or window_sum < best_sum):
                best, best_sum = run[i - hours + 1 : i + 1], window_sum
    if best is None:
        return None
    return CheapestWindow(
        start=best[0].start_utc,
        end=best[-1].start_utc + timedelta(minutes=HOURLY),
        average_price=_average([p.price_eur_per_kwh for p in best]),
        points=best,
    )


def get_daily_stats(session: Session, day: date, source: str = DEFAULT_SOURCE) -> DailyStats:
    points = get_prices(session, day, source)
    if not points:
        raise NoPriceDataError(day, source)
    return summarize_prices(points, expected_point_count(day))


def get_cheapest_window(
    session: Session, day: date, hours: int, source: str = DEFAULT_SOURCE
) -> CheapestWindow:
    points = get_prices(session, day, source)
    if not points:
        raise NoPriceDataError(day, source)
    window = find_cheapest_window(points, hours)
    if window is None:
        longest_run = max(len(run) for run in split_into_runs(points))
        raise InsufficientDataError(
            f"Requested {hours} consecutive hours, but the longest run of consecutive "
            f"price data for {day.isoformat()} is {longest_run} hours"
        )
    return window

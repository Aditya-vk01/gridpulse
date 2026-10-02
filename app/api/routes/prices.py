from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import PricePoint
from app.schemas import CheapestWindowOut, DailyStatsOut, ErrorOut, PriceListOut, PricePointOut
from app.services import prices as service
from app.sources.base import AMSTERDAM

router = APIRouter(prefix="/prices", tags=["prices"])

SessionDep = Annotated[Session, Depends(get_session)]
DayQuery = Annotated[
    date | None,
    Query(
        alias="date",
        description="Dutch calendar day (Europe/Amsterdam), YYYY-MM-DD. Defaults to today.",
    ),
]
NOT_FOUND = {404: {"model": ErrorOut, "description": "No price data for this date"}}


def _resolve_day(day: date | None) -> date:
    return day or datetime.now(AMSTERDAM).date()


def _point_out(point: PricePoint) -> PricePointOut:
    return PricePointOut(
        start=point.start_utc,
        end=point.start_utc + timedelta(minutes=point.resolution_minutes),
        price_eur_per_kwh=point.price_eur_per_kwh,
        includes_vat=point.includes_vat,
    )


@router.get(
    "",
    summary="Hourly prices for a day",
    description="All hourly day-ahead prices for one Dutch calendar day, ordered by time. "
    "A day has 23, 24 or 25 hours depending on daylight saving time.",
    response_model=PriceListOut,
    responses=NOT_FOUND,
)
def list_prices(session: SessionDep, day: DayQuery = None) -> PriceListOut:
    day = _resolve_day(day)
    points = service.get_prices(session, day)
    if not points:
        raise HTTPException(404, str(service.NoPriceDataError(day, service.DEFAULT_SOURCE)))
    return PriceListOut(
        date=day, source=service.DEFAULT_SOURCE, prices=[_point_out(p) for p in points]
    )


@router.get(
    "/stats",
    summary="Daily price statistics",
    description="Minimum, maximum and average price for a Dutch calendar day, with the "
    "times of the extremes. `is_complete` is false if hours are missing.",
    response_model=DailyStatsOut,
    responses=NOT_FOUND,
)
def daily_stats(session: SessionDep, day: DayQuery = None) -> DailyStatsOut:
    day = _resolve_day(day)
    try:
        stats = service.get_daily_stats(session, day)
    except service.NoPriceDataError as exc:
        raise HTTPException(404, str(exc)) from exc
    return DailyStatsOut(
        date=day,
        source=service.DEFAULT_SOURCE,
        count=stats.count,
        expected_count=stats.expected_count,
        is_complete=stats.is_complete,
        min_price_eur_per_kwh=stats.min_price,
        min_price_start=stats.min_price_start,
        max_price_eur_per_kwh=stats.max_price,
        max_price_start=stats.max_price_start,
        average_price_eur_per_kwh=stats.average_price,
    )


@router.get(
    "/cheapest",
    summary="Cheapest block of consecutive hours",
    description="The block of `hours` consecutive hours with the lowest average price on a "
    "Dutch calendar day, e.g. to schedule an EV charger or heat pump. Blocks never span "
    "missing hours. Returns 404 if no block of that length exists.",
    response_model=CheapestWindowOut,
    responses={
        404: {
            "model": ErrorOut,
            "description": "No price data, or not enough consecutive hours of data",
        }
    },
)
def cheapest_window(
    session: SessionDep,
    day: DayQuery = None,
    hours: Annotated[int, Query(ge=1, le=12, description="Block length in hours")] = 3,
) -> CheapestWindowOut:
    day = _resolve_day(day)
    try:
        window = service.get_cheapest_window(session, day, hours)
    except (service.NoPriceDataError, service.InsufficientDataError) as exc:
        raise HTTPException(404, str(exc)) from exc
    return CheapestWindowOut(
        date=day,
        source=service.DEFAULT_SOURCE,
        hours=hours,
        start=window.start,
        end=window.end,
        average_price_eur_per_kwh=window.average_price,
        prices=[_point_out(p) for p in window.points],
    )

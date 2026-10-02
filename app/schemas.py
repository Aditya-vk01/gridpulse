"""API response models.

All timestamps are returned in Europe/Amsterdam time with their UTC offset, e.g.
``2026-10-01T00:00:00+02:00``. On daylight-saving days the offset tells the two 02:00
hours apart. Prices are ``Decimal`` and are serialised as JSON strings (e.g.
``"0.1609025000"``) so no precision is lost to floating point.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict

from app.sources.base import AMSTERDAM


def _to_amsterdam(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("naive datetimes are not allowed; store and pass UTC-aware values")
    return dt.astimezone(AMSTERDAM)


AmsterdamDatetime = Annotated[datetime, AfterValidator(_to_amsterdam)]


class PricePointOut(BaseModel):
    start: AmsterdamDatetime
    end: AmsterdamDatetime
    price_eur_per_kwh: Decimal
    includes_vat: bool


class PriceListOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "date": "2026-10-01",
                    "source": "energyzero",
                    "prices": [
                        {
                            "start": "2026-10-01T00:00:00+02:00",
                            "end": "2026-10-01T01:00:00+02:00",
                            "price_eur_per_kwh": "0.1552924960",
                            "includes_vat": False,
                        }
                    ],
                }
            ]
        }
    )

    date: date
    source: str
    prices: list[PricePointOut]


class DailyStatsOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "date": "2026-10-01",
                    "source": "energyzero",
                    "count": 24,
                    "expected_count": 24,
                    "is_complete": True,
                    "min_price_eur_per_kwh": "0.1552924960",
                    "min_price_start": "2026-10-01T00:00:00+02:00",
                    "max_price_eur_per_kwh": "0.3005425040",
                    "max_price_start": "2026-10-01T19:00:00+02:00",
                    "average_price_eur_per_kwh": "0.1969766678",
                }
            ]
        }
    )

    date: date
    source: str
    count: int
    expected_count: int
    is_complete: bool
    min_price_eur_per_kwh: Decimal
    min_price_start: AmsterdamDatetime
    max_price_eur_per_kwh: Decimal
    max_price_start: AmsterdamDatetime
    average_price_eur_per_kwh: Decimal


class CheapestWindowOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "date": "2026-10-01",
                    "source": "energyzero",
                    "hours": 3,
                    "start": "2026-10-01T13:00:00+02:00",
                    "end": "2026-10-01T16:00:00+02:00",
                    "average_price_eur_per_kwh": "0.1585058350",
                    "prices": [
                        {
                            "start": "2026-10-01T13:00:00+02:00",
                            "end": "2026-10-01T14:00:00+02:00",
                            "price_eur_per_kwh": "0.1585800000",
                            "includes_vat": False,
                        },
                        {
                            "start": "2026-10-01T14:00:00+02:00",
                            "end": "2026-10-01T15:00:00+02:00",
                            "price_eur_per_kwh": "0.1581600000",
                            "includes_vat": False,
                        },
                        {
                            "start": "2026-10-01T15:00:00+02:00",
                            "end": "2026-10-01T16:00:00+02:00",
                            "price_eur_per_kwh": "0.1587775050",
                            "includes_vat": False,
                        },
                    ],
                }
            ]
        }
    )

    date: date
    source: str
    hours: int
    start: AmsterdamDatetime
    end: AmsterdamDatetime
    average_price_eur_per_kwh: Decimal
    prices: list[PricePointOut]


class ErrorOut(BaseModel):
    detail: str

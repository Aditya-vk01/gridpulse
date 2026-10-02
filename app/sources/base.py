from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

AMSTERDAM = ZoneInfo("Europe/Amsterdam")


@dataclass(frozen=True)
class PriceRecord:
    start_utc: datetime
    resolution_minutes: int
    price_eur_per_kwh: Decimal
    includes_vat: bool


class PriceSource(ABC):
    name: str

    @abstractmethod
    def fetch_day(self, day: date) -> list[PriceRecord]:
        """Return all prices for one Dutch calendar day (Europe/Amsterdam)."""


def dutch_day_window(day: date) -> tuple[datetime, datetime]:
    """Return [start, end) in UTC for a Dutch calendar day; 23, 24 or 25 hours long."""
    start_local = datetime.combine(day, time.min, tzinfo=AMSTERDAM)
    end_local = datetime.combine(day + timedelta(days=1), time.min, tzinfo=AMSTERDAM)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)

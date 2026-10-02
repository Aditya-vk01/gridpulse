import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx

from app.sources.base import PriceRecord, PriceSource, dutch_day_window

logger = logging.getLogger(__name__)

BASE_URL = "https://api.energyzero.nl/v1/energyprices"
HOURLY_INTERVAL = 4  # EnergyZero's code for hourly prices
RESOLUTION_MINUTES = 60
USAGE_TYPE_ELECTRICITY = 1
MAX_PRICE_DECIMALS = 10  # matches the scale of price_points.price_eur_per_kwh


class EnergyZeroError(Exception):
    """The EnergyZero API could not be reached or returned an error."""


class EnergyZeroDataError(EnergyZeroError):
    """The EnergyZero API returned data in an unexpected format."""


def _to_api_timestamp(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class EnergyZeroSource(PriceSource):
    name = "energyzero"

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        max_retries: int = 3,
        backoff_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client or httpx.Client(timeout=10.0)
        self._max_retries = max_retries
        self._backoff_seconds = backoff_seconds
        self._sleep = sleep

    def fetch_day(self, day: date) -> list[PriceRecord]:
        start_utc, end_utc = dutch_day_window(day)
        params = {
            "fromDate": _to_api_timestamp(start_utc),
            "tillDate": _to_api_timestamp(end_utc - timedelta(milliseconds=1)),
            "interval": HOURLY_INTERVAL,
            "usageType": USAGE_TYPE_ELECTRICITY,
            "inclBtw": "false",
        }
        payload = self._get_json(params)
        records = [r for r in self._parse(payload) if start_utc <= r.start_utc < end_utc]

        expected = int((end_utc - start_utc) / timedelta(minutes=RESOLUTION_MINUTES))
        if records and len(records) != expected:
            logger.warning(
                "EnergyZero returned %d points for %s, expected %d",
                len(records),
                day,
                expected,
            )
        return records

    def _get_json(self, params: dict[str, Any]) -> Any:
        attempt = 0
        while True:
            try:
                response = self._client.get(BASE_URL, params=params)
                response.raise_for_status()
                return json.loads(response.text, parse_float=Decimal)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                retryable = not isinstance(exc, httpx.HTTPStatusError) or (
                    exc.response.status_code >= 500
                )
                if not retryable or attempt >= self._max_retries:
                    raise EnergyZeroError(f"EnergyZero request failed: {exc!r}") from exc
                delay = self._backoff_seconds * 2**attempt
                attempt += 1
                logger.warning(
                    "EnergyZero request failed (%r), retry %d/%d in %.1fs",
                    exc,
                    attempt,
                    self._max_retries,
                    delay,
                )
                self._sleep(delay)
            except json.JSONDecodeError as exc:
                raise EnergyZeroDataError(f"EnergyZero returned invalid JSON: {exc}") from exc

    @staticmethod
    def _parse(payload: Any) -> list[PriceRecord]:
        if not isinstance(payload, dict) or not isinstance(payload.get("Prices"), list):
            raise EnergyZeroDataError("Expected a JSON object with a 'Prices' list")

        records = []
        for i, point in enumerate(payload["Prices"]):
            try:
                start = datetime.fromisoformat(point["readingDate"])
                price = point["price"]
            except (TypeError, KeyError, ValueError) as exc:
                raise EnergyZeroDataError(f"Malformed price point at index {i}: {point!r}") from exc
            if start.tzinfo is None:
                raise EnergyZeroDataError(f"Timestamp without timezone at index {i}: {point!r}")
            if isinstance(price, bool) or not isinstance(price, Decimal | int):
                raise EnergyZeroDataError(f"Non-numeric price at index {i}: {point!r}")
            price = Decimal(price)
            # Trailing zeros don't count: 0.10000000000 fits exactly, 0.12345678901 doesn't.
            if price.normalize().as_tuple().exponent < -MAX_PRICE_DECIMALS:
                raise EnergyZeroDataError(
                    f"Price at index {i} has more than {MAX_PRICE_DECIMALS} decimals "
                    f"and cannot be stored without rounding: {point!r}"
                )
            records.append(
                PriceRecord(
                    start_utc=start.astimezone(UTC),
                    resolution_minutes=RESOLUTION_MINUTES,
                    price_eur_per_kwh=price,
                    includes_vat=False,
                )
            )
        return records

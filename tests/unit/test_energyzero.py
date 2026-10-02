import logging
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest

from app.sources.energyzero import EnergyZeroDataError, EnergyZeroError, EnergyZeroSource

DAY = date(2026, 10, 1)  # Dutch day = 2026-09-30T22:00Z .. 2026-10-01T22:00Z


def prices_json(*points: tuple[str, str]) -> str:
    """Raw JSON text, so prices keep every digit exactly as the API would send them."""
    items = ",".join(f'{{"readingDate":"{ts}","price":{price}}}' for ts, price in points)
    return f'{{"Prices":[{items}]}}'


def full_day_json() -> str:
    return prices_json(
        *[(f"2026-09-30T{h:02d}:00:00Z", "0.1") for h in (22, 23)],
        *[(f"2026-10-01T{h:02d}:00:00Z", "0.1") for h in range(22)],
    )


def make_source(*responses):
    """A source whose HTTP calls return (or raise) `responses` in order."""
    calls: list[httpx.Request] = []
    sleeps: list[float] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return EnergyZeroSource(client, sleep=sleeps.append), calls, sleeps


def test_parses_prices_as_decimal_in_utc():
    body = prices_json(("2026-09-30T22:00:00Z", "0.1609025"), ("2026-09-30T23:00:00Z", "0.162"))
    source, calls, _ = make_source(httpx.Response(200, text=body))

    records = source.fetch_day(DAY)

    assert [r.start_utc for r in records] == [
        datetime(2026, 9, 30, 22, tzinfo=UTC),
        datetime(2026, 9, 30, 23, tzinfo=UTC),
    ]
    assert records[0].price_eur_per_kwh == Decimal("0.1609025")
    assert all(type(r.price_eur_per_kwh) is Decimal for r in records)
    assert all(r.resolution_minutes == 60 and r.includes_vat is False for r in records)
    params = calls[0].url.params
    assert params["fromDate"] == "2026-09-30T22:00:00.000Z"
    assert params["tillDate"] == "2026-10-01T21:59:59.999Z"
    assert (params["interval"], params["usageType"], params["inclBtw"]) == ("4", "1", "false")


def test_filters_points_outside_the_dutch_day():
    body = prices_json(
        ("2026-09-30T21:00:00Z", "1"),  # 23:00 on the previous Dutch day
        ("2026-09-30T22:00:00Z", "2"),  # first hour of the day
        ("2026-10-01T21:00:00Z", "3"),  # last hour of the day
        ("2026-10-01T22:00:00Z", "4"),  # midnight: already the next day (end is exclusive)
    )
    source, _, _ = make_source(httpx.Response(200, text=body))

    assert [r.price_eur_per_kwh for r in source.fetch_day(DAY)] == [Decimal(2), Decimal(3)]


def test_retries_5xx_with_exponential_backoff_then_succeeds():
    source, calls, sleeps = make_source(
        httpx.Response(503), httpx.Response(502), httpx.Response(200, text=full_day_json())
    )

    assert len(source.fetch_day(DAY)) == 24
    assert len(calls) == 3
    assert sleeps == [1.0, 2.0]


def test_gives_up_after_three_retries_on_persistent_500():
    source, calls, sleeps = make_source(httpx.Response(500))

    with pytest.raises(EnergyZeroError):
        source.fetch_day(DAY)
    assert len(calls) == 4
    assert sleeps == [1.0, 2.0, 4.0]


def test_does_not_retry_4xx():
    source, calls, sleeps = make_source(httpx.Response(404))

    with pytest.raises(EnergyZeroError):
        source.fetch_day(DAY)
    assert len(calls) == 1
    assert sleeps == []


def test_retries_timeout_then_succeeds():
    source, calls, _ = make_source(
        httpx.ReadTimeout("timed out"), httpx.Response(200, text=full_day_json())
    )

    assert len(source.fetch_day(DAY)) == 24
    assert len(calls) == 2


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("not json", id="invalid-json"),
        pytest.param("[]", id="not-an-object"),
        pytest.param('{"Prices": "nope"}', id="prices-not-a-list"),
        pytest.param('{"Prices": [{"price": 0.1}]}', id="missing-readingDate"),
        pytest.param('{"Prices": [{"readingDate": "2026-10-01T00:00:00Z"}]}', id="missing-price"),
        pytest.param('{"Prices": [{"readingDate": "yesterday", "price": 0.1}]}', id="bad-date"),
        pytest.param(
            '{"Prices": [{"readingDate": "2026-10-01T00:00:00", "price": 0.1}]}', id="naive-ts"
        ),
        pytest.param(
            '{"Prices": [{"readingDate": "2026-10-01T00:00:00Z", "price": "0.1"}]}',
            id="price-string",
        ),
        pytest.param(
            '{"Prices": [{"readingDate": "2026-10-01T00:00:00Z", "price": true}]}',
            id="price-bool",
        ),
    ],
)
def test_malformed_data_raises_data_error(body):
    source, calls, _ = make_source(httpx.Response(200, text=body))

    with pytest.raises(EnergyZeroDataError):
        source.fetch_day(DAY)
    assert len(calls) == 1  # bad data is not retried


@pytest.mark.parametrize("price", ["0.160087496", "0.10000000000"])
def test_precision_guard_accepts_values_that_fit_exactly(price):
    source, _, _ = make_source(
        httpx.Response(200, text=prices_json(("2026-10-01T00:00:00Z", price)))
    )

    assert source.fetch_day(DAY)[0].price_eur_per_kwh == Decimal(price)


def test_precision_guard_rejects_values_that_would_be_rounded():
    source, _, _ = make_source(
        httpx.Response(200, text=prices_json(("2026-10-01T00:00:00Z", "0.12345678901")))
    )

    with pytest.raises(EnergyZeroDataError, match="more than 10 decimals"):
        source.fetch_day(DAY)


def test_empty_response_returns_empty_list():
    source, _, _ = make_source(httpx.Response(200, text='{"Prices": []}'))

    assert source.fetch_day(DAY) == []


def test_warns_when_point_count_does_not_match_day_length(caplog):
    source, _, _ = make_source(
        httpx.Response(200, text=prices_json(("2026-10-01T00:00:00Z", "0.1")))
    )

    with caplog.at_level(logging.WARNING, logger="app.sources.energyzero"):
        source.fetch_day(DAY)
    assert "returned 1 points for 2026-10-01, expected 24" in caplog.text

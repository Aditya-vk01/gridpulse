from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.jobs.ingest import ingest_day, main
from app.models import IngestionRun, PricePoint
from app.sources.base import PriceRecord, PriceSource, dutch_day_window

pytestmark = pytest.mark.integration

DAY = date(2026, 10, 1)


class FakeSource(PriceSource):
    name = "fake"

    def __init__(self, records: list[PriceRecord] | None = None, error: Exception | None = None):
        self.records = records or []
        self.error = error

    def fetch_day(self, day: date) -> list[PriceRecord]:
        if self.error:
            raise self.error
        return self.records


def records_for(day: date, prices: list[str]) -> list[PriceRecord]:
    start_utc, _ = dutch_day_window(day)
    return [
        PriceRecord(start_utc + timedelta(hours=i), 60, Decimal(p), includes_vat=False)
        for i, p in enumerate(prices)
    ]


def stored_prices(session) -> list[Decimal]:
    return list(
        session.scalars(
            select(PricePoint.price_eur_per_kwh)
            .where(PricePoint.source == "fake")
            .order_by(PricePoint.start_utc)
        )
    )


def test_success_writes_rows(db_session):
    run = ingest_day(db_session, FakeSource(records_for(DAY, ["0.1609025"] * 24)), DAY)

    assert (run.status, run.points_written, run.error_message) == ("success", 24, None)
    assert run.finished_at is not None
    assert stored_prices(db_session) == [Decimal("0.1609025")] * 24


def test_rerun_is_idempotent(db_session):
    source = FakeSource(records_for(DAY, ["0.1"] * 24))

    first = ingest_day(db_session, source, DAY)
    second = ingest_day(db_session, source, DAY)

    assert len(stored_prices(db_session)) == 24
    assert [first.status, second.status] == ["success", "success"]
    assert db_session.scalar(select(func.count()).select_from(IngestionRun)) == 2


def test_upsert_applies_corrected_prices(db_session):
    ingest_day(db_session, FakeSource(records_for(DAY, ["0.1"] * 24)), DAY)
    corrected = ["0.1"] * 24
    corrected[5] = "0.2500000001"

    ingest_day(db_session, FakeSource(records_for(DAY, corrected)), DAY)

    prices = stored_prices(db_session)
    assert len(prices) == 24
    assert prices[5] == Decimal("0.2500000001")


def test_empty_source_gives_no_data(db_session):
    run = ingest_day(db_session, FakeSource([]), DAY)

    assert (run.status, run.points_written) == ("no_data", 0)
    assert run.finished_at is not None


def test_raising_source_gives_failed_run(db_session):
    run = ingest_day(db_session, FakeSource(error=RuntimeError("API down")), DAY)

    db_session.expire_all()  # read back what was actually committed
    stored = db_session.get(IngestionRun, run.id)
    assert stored.status == "failed"
    assert stored.error_message == "RuntimeError: API down"
    assert stored.finished_at is not None
    assert stored_prices(db_session) == []


def test_failed_upsert_rolls_back_and_records_failure(db_session):
    # A price too large for numeric(16,10) makes the INSERT itself fail.
    run = ingest_day(db_session, FakeSource(records_for(DAY, ["1000000"])), DAY)

    assert run.status == "failed"
    assert "NumericValueOutOfRange" in run.error_message
    assert stored_prices(db_session) == []


@pytest.mark.parametrize(
    ("source", "exit_code"),
    [
        pytest.param(FakeSource(error=RuntimeError("boom")), 1, id="failed-run-exits-1"),
        pytest.param(FakeSource([]), 0, id="no-data-exits-0"),
        pytest.param(FakeSource(records_for(DAY, ["0.1"] * 24)), 0, id="success-exits-0"),
    ],
)
def test_cli_exit_code(session_factory, source, exit_code):
    argv = ["--date", "2026-10-01"]

    assert main(argv, source=source, session_factory=session_factory) == exit_code

import argparse
import logging
import sys
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import IngestionRun, PricePoint
from app.sources.base import AMSTERDAM, PriceSource

logger = logging.getLogger(__name__)

STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_NO_DATA = "no_data"
STATUS_FAILED = "failed"


def ingest_day(session: Session, source: PriceSource, day: date) -> IngestionRun:
    run = IngestionRun(source=source.name, target_date=day, status=STATUS_RUNNING)
    session.add(run)
    session.commit()
    logger.info("Run %d: ingesting %s from %s", run.id, day, source.name)

    try:
        records = source.fetch_day(day)
        if records:
            stmt = insert(PricePoint).values(
                [
                    {
                        "source": source.name,
                        "start_utc": r.start_utc,
                        "resolution_minutes": r.resolution_minutes,
                        "price_eur_per_kwh": r.price_eur_per_kwh,
                        "includes_vat": r.includes_vat,
                    }
                    for r in records
                ]
            )
            stmt = stmt.on_conflict_do_update(
                constraint="uq_price_points_source_start_resolution",
                set_={
                    "price_eur_per_kwh": stmt.excluded.price_eur_per_kwh,
                    "includes_vat": stmt.excluded.includes_vat,
                    "ingested_at": func.now(),
                },
            )
            session.execute(stmt)
        run.points_written = len(records)
        run.status = STATUS_SUCCESS if records else STATUS_NO_DATA
        run.finished_at = datetime.now(UTC)
        session.commit()
        logger.info("Run %d: %s, %d points written", run.id, run.status, run.points_written)
    except Exception as exc:
        session.rollback()
        logger.exception("Run %d: failed to ingest %s", run.id, day)
        run.status = STATUS_FAILED
        run.error_message = f"{type(exc).__name__}: {exc}"
        run.finished_at = datetime.now(UTC)
        session.commit()
    return run


def _days_to_ingest(args: argparse.Namespace) -> list[date]:
    today = datetime.now(AMSTERDAM).date()
    if args.date:
        return [args.date]
    if args.days:
        return [today - timedelta(days=n) for n in reversed(range(args.days))]
    return [today, today + timedelta(days=1)]


def _positive_int(value: str) -> int:
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return n


def main(
    argv: list[str] | None = None,
    *,
    source: PriceSource | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> int:
    """CLI entry point. `source` and `session_factory` can be injected for tests."""
    parser = argparse.ArgumentParser(description="Ingest Dutch day-ahead electricity prices.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--date", type=date.fromisoformat, help="Dutch calendar day, YYYY-MM-DD")
    group.add_argument(
        "--days", type=_positive_int, help="backfill the last N Dutch days, up to today"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    # Imported here so --help works without a configured database.
    from app.db import SessionLocal
    from app.sources.energyzero import EnergyZeroSource

    source = source or EnergyZeroSource()
    session_factory = session_factory or SessionLocal
    failed = 0
    with session_factory() as session:
        for day in _days_to_ingest(args):
            if ingest_day(session, source, day).status == STATUS_FAILED:
                failed += 1
    if failed:
        logger.error("%d run(s) failed", failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

import os

# Set before any app import: app.db builds its engine from Settings at import time.
# Port 1 refuses connections, so a test that accidentally uses the real engine fails
# fast instead of touching a developer's database.
os.environ["DATABASE_URL"] = "postgresql+psycopg://unused:unused@127.0.0.1:1/unused"

from collections.abc import Callable, Collection, Iterator  # noqa: E402
from datetime import date, timedelta  # noqa: E402
from decimal import Decimal  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy import Connection, Engine, create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.models import PricePoint  # noqa: E402
from app.sources.base import dutch_day_window  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

MakePoints = Callable[..., list[PricePoint]]


@pytest.fixture
def make_points() -> MakePoints:
    """Build unsaved hourly PricePoints from Dutch midnight of `day`, consecutive in UTC.

    Indices in `skip` are left out, creating gaps in the data.
    """

    def _make(
        day: date, prices: list[str], skip: Collection[int] = (), source: str = "energyzero"
    ) -> list[PricePoint]:
        start_utc, _ = dutch_day_window(day)
        return [
            PricePoint(
                source=source,
                start_utc=start_utc + timedelta(hours=i),
                resolution_minutes=60,
                price_eur_per_kwh=Decimal(price),
                includes_vat=False,
            )
            for i, price in enumerate(prices)
            if i not in skip
        ]

    return _make


# --- Integration fixtures: only started when an integration test requests them ---


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer("postgres:17", driver="psycopg") as pg:
        # On Windows "localhost" tries IPv6 first and stalls against Docker's IPv4-only port.
        yield pg.get_connection_url().replace("@localhost:", "@127.0.0.1:")


@pytest.fixture(scope="session")
def engine(postgres_url: str) -> Iterator[Engine]:
    """Migrate the container with the real Alembic migrations, not metadata.create_all()."""
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", postgres_url.replace("%", "%%"))
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")

    engine = create_engine(postgres_url)
    yield engine
    engine.dispose()


@pytest.fixture
def connection(engine: Engine) -> Iterator[Connection]:
    """One outer transaction per test, always rolled back: tests never see each other's data."""
    with engine.connect() as conn:
        transaction = conn.begin()
        yield conn
        transaction.rollback()


@pytest.fixture
def session_factory(connection: Connection) -> sessionmaker[Session]:
    # Session commits become SAVEPOINT releases inside the outer transaction.
    return sessionmaker(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )


@pytest.fixture
def db_session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as session:
        yield session

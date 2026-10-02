from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PricePoint(Base):
    __tablename__ = "price_points"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "start_utc",
            "resolution_minutes",
            name="uq_price_points_source_start_resolution",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(String(50))
    start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    resolution_minutes: Mapped[int] = mapped_column(Integer)
    price_eur_per_kwh: Mapped[Decimal] = mapped_column(Numeric(16, 10))
    includes_vat: Mapped[bool] = mapped_column(Boolean)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(String(50))
    target_date: Mapped[date] = mapped_column(Date)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20))
    points_written: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text)

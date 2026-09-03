from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AdMetricRealtime(Base):
    __tablename__ = "ad_metric_realtime"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    campaign_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True,
    )
    dimension: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    dim_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    time_window: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    window_start: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )
    impression: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default="0",
    )
    click: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default="0",
    )
    cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        server_default="0",
    )
    lead: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )
    valid_lead: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )
    order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )
    ctr: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 6),
    )
    cpc: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2),
    )
    cpa: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2),
    )
    roi: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class BudgetConsumption(Base):
    __tablename__ = "budget_consumption"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    campaign_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True,
    )
    target_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    target_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    budget_total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )
    cost_total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        server_default="0",
    )
    cost_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2),
    )
    remaining: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
    )
    alert_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default="正常",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=text("CURRENT_TIMESTAMP"),
    )
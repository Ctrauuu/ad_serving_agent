from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    Numeric,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AdPlan(Base):
    __tablename__ = "ad_plan"

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
    strategy_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    channel_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    budget_daily: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )
    budget_total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )
    bid_strategy: Mapped[str | None] = mapped_column(
        String(64),
    )
    start_time: Mapped[datetime | None] = mapped_column(
        DateTime,
    )
    end_time: Mapped[datetime | None] = mapped_column(
        DateTime,
    )
    ad_platform_task_id: Mapped[str | None] = mapped_column(
        String(128),
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="待创建",
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(
        String(512),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=text("CURRENT_TIMESTAMP"),
    )


class AdGroup(Base):
    __tablename__ = "ad_group"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    ad_plan_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True,
    )
    campaign_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    audience_id: Mapped[int | None] = mapped_column(
        BigInteger,
    )
    creative_id: Mapped[int | None] = mapped_column(
        BigInteger,
    )
    bid: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
    )
    budget_daily: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )
    ad_platform_group_id: Mapped[str | None] = mapped_column(
        String(128),
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="待创建",
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(
        String(512),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=text("CURRENT_TIMESTAMP"),
    )


class Keyword(Base):
    __tablename__ = "keyword"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    ad_group_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True,
    )
    word: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    match_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="短语匹配",
    )
    bid: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
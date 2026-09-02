from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Strategy(Base):
    __tablename__ = "strategy"

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
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="1",
    )
    channel_mix: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
    )
    budget_split: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )
    ad_group_structure: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
    )
    audience_plan: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    keyword_plan: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    creative_test_plan: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    bid_strategy: Mapped[str | None] = mapped_column(String(64))
    expected_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    risk_notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="待确认",
    )
    confirmed_by: Mapped[int | None] = mapped_column(BigInteger)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
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


class StrategyEvidence(Base):
    __tablename__ = "strategy_evidence"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    strategy_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True,
    )
    evidence_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_item: Mapped[str] = mapped_column(String(128), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(128))
    vector_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    JSON,
    Numeric,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MonitorRule(Base):
    __tablename__ = "monitor_rule"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    rule_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    metric: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    condition_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )
    stage: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="全部",
    )
    channel_scope: Mapped[str | None] = mapped_column(
        String(128),
    )
    risk_level: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        server_default="中",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="1",
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


class AnomalyRecord(Base):
    __tablename__ = "anomaly_record"
    __table_args__ = (
        Index(
            "idx_campaign_status",
            "campaign_id",
            "status",
        ),
        Index(
            "idx_target",
            "target_type",
            "target_id",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    campaign_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    target_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    target_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    anomaly_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    metric: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    metric_value: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
    )
    baseline_value: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
    )
    rule_id: Mapped[int | None] = mapped_column(
        BigInteger,
    )
    severity: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        server_default="中",
    )
    evidence_json: Mapped[
        dict[str, Any] | None
    ] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default="待归因",
    )
    detected_at: Mapped[datetime] = mapped_column(
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

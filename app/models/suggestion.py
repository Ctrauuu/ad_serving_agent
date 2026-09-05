from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    JSON,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class InterventionSuggestion(Base):
    """投放干预建议。"""

    __tablename__ = "intervention_suggestion"
    __table_args__ = (
        Index("idx_anomaly", "anomaly_id"),
        Index(
            "idx_campaign_status",
            "campaign_id",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    anomaly_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
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
    cause_id: Mapped[int | None] = mapped_column(
        BigInteger,
    )
    action_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    action_params: Mapped[dict[str, Any]] = (
        mapped_column(
            JSON,
            nullable=False,
        )
    )
    metric_evidence: Mapped[
        dict[str, Any] | None
    ] = mapped_column(JSON)
    triggered_rule: Mapped[str | None] = (
        mapped_column(String(128))
    )
    expected_impact: Mapped[
        dict[str, Any] | None
    ] = mapped_column(JSON)
    risk_notes: Mapped[str | None] = (
        mapped_column(Text)
    )
    risk_level: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        server_default="中",
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="1",
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default="待提交",
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

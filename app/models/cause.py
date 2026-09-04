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
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AnomalyCause(Base):
    """异常原因假设。"""

    __tablename__ = "anomaly_cause"
    __table_args__ = (
        Index("idx_anomaly", "anomaly_id"),
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
    cause_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    hypothesis: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(4, 3),
        nullable=False,
    )
    evidence_sources: Mapped[
        list[dict[str, Any]] | None
    ] = mapped_column(JSON)
    data_sufficient: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class SalesFeedback(Base):
    """销售侧回传的线索质量信号。"""

    __tablename__ = "sales_feedback"
    __table_args__ = (
        Index("idx_campaign", "campaign_id"),
        Index("idx_group", "ad_group_id"),
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
    ad_group_id: Mapped[int | None] = mapped_column(
        BigInteger,
    )
    lead_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    lead_quality: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    invalid_reason: Mapped[str | None] = mapped_column(
        String(128),
    )
    customer_profile_match: Mapped[bool | None] = (
        mapped_column(Boolean)
    )
    deal_cycle_days: Mapped[int | None] = mapped_column()
    feedback_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )


class CaseLibrary(Base):
    """用于召回的历史投放案例。"""

    __tablename__ = "case_library"
    __table_args__ = (
        Index("idx_type", "case_type"),
        Index("idx_effectiveness", "effectiveness"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    case_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    campaign_id: Mapped[int | None] = mapped_column(
        BigInteger,
    )
    scene_desc: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    anomaly_type: Mapped[str | None] = mapped_column(
        String(32),
    )
    cause: Mapped[str | None] = mapped_column(
        String(128),
    )
    action: Mapped[str | None] = mapped_column(
        String(128),
    )
    effectiveness: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    conclusion: Mapped[str | None] = mapped_column(
        Text,
    )
    vector_id: Mapped[str | None] = mapped_column(
        String(64),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
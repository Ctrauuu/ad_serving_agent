from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ApprovalRecord(Base):
    """干预建议的风险审批记录。"""

    __tablename__ = "approval_record"
    __table_args__ = (
        Index("idx_status", "status"),
        Index("idx_approver", "approver_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    suggestion_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    campaign_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    risk_level: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
    )
    auto_execute: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="0",
    )
    approver_id: Mapped[int | None] = mapped_column(
        BigInteger,
    )
    approval_opinion: Mapped[str | None] = mapped_column(
        Text,
    )
    reject_reason: Mapped[str | None] = mapped_column(
        String(512),
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default="待审批",
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime,
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    JSON,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ActionExecution(Base):
    """广告平台动作执行与回滚记录。"""

    __tablename__ = "action_execution"
    __table_args__ = (
        Index("idx_campaign", "campaign_id"),
        Index("idx_suggestion", "suggestion_id"),
        Index("idx_status", "status"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    approval_id: Mapped[int | None] = mapped_column(
        BigInteger,
    )
    suggestion_id: Mapped[int] = mapped_column(
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
    action_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    action_params: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )
    before_state: Mapped[
        dict[str, Any] | None
    ] = mapped_column(JSON)
    after_state: Mapped[
        dict[str, Any] | None
    ] = mapped_column(JSON)
    tool_name: Mapped[str | None] = mapped_column(
        String(64),
    )
    tool_result: Mapped[
        dict[str, Any] | None
    ] = mapped_column(JSON)
    executor_id: Mapped[int | None] = mapped_column(
        BigInteger,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default="待执行",
    )
    error_message: Mapped[str | None] = mapped_column(
        String(512),
    )
    rollback_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default="不适用",
    )
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

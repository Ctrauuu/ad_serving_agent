from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ReviewReport(Base):
    """活动投放复盘报告。"""

    __tablename__ = "review_report"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id",
            "version",
            name="uk_campaign_version",
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
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="1",
    )
    overall_metrics: Mapped[
        dict[str, Any] | None
    ] = mapped_column(JSON)
    strategy_evaluation: Mapped[
        dict[str, Any] | None
    ] = mapped_column(JSON)
    intervention_evaluation: Mapped[
        dict[str, Any] | None
    ] = mapped_column(JSON)
    reusable_conclusion: Mapped[str | None] = (
        mapped_column(Text)
    )
    lessons: Mapped[str | None] = mapped_column(Text)
    improvement: Mapped[str | None] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class KnowledgeDoc(Base):
    """知识库文档元数据。"""

    __tablename__ = "knowledge_doc"
    __table_args__ = (
        Index("idx_type", "doc_type"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    title: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
    )
    doc_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    source_ref: Mapped[str | None] = mapped_column(
        String(128),
    )
    ragflow_doc_id: Mapped[str | None] = mapped_column(
        String(64),
    )
    chunk_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )
    parse_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default="待解析",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

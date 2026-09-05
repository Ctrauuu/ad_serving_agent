from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


CauseEvidenceType = Literal[
    "metric",
    "creative",
    "audience",
    "channel",
    "landing_page",
    "sales_feedback",
    "case",
    "ad_group",
    "anomaly",
    "metric_snapshot",
]


class CauseEvidence(BaseModel):
    """单条可追溯的归因证据。"""

    type: CauseEvidenceType
    ref: str = Field(
        min_length=1,
        max_length=128,
    )
    description: str | None = Field(
        default=None,
        max_length=512,
    )


class CauseHypothesis(BaseModel):
    """大模型生成的单个原因假设。"""

    cause_type: str = Field(
        min_length=1,
        max_length=64,
    )
    hypothesis: str = Field(
        min_length=1,
        max_length=2000,
    )
    confidence: Decimal = Field(
        ge=Decimal("0"),
        le=Decimal("1"),
    )
    evidence_sources: list[CauseEvidence] = Field(
        min_length=1,
    )


class CauseAnalysisOutput(BaseModel):
    """大模型归因结果。"""

    causes: list[CauseHypothesis] = Field(
        min_length=2,
        max_length=5,
    )


class AnomalyCauseRead(BaseModel):
    """异常原因查询结果。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    anomaly_id: int
    cause_type: str
    hypothesis: str
    confidence: Decimal
    evidence_sources: list[CauseEvidence] | None
    data_sufficient: bool
    created_at: datetime


class CauseAnalysisResult(BaseModel):
    """归因分析接口响应。"""

    anomaly_id: int
    data_sufficient: bool
    has_historical_cases: bool
    causes: list[AnomalyCauseRead]


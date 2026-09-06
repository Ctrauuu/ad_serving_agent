from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ReviewCaseType = Literal[
    "strategy",
    "anomaly",
    "intervention",
]

CaseEffectiveness = Literal["有效", "失败"]


class ReviewReportRead(BaseModel):
    """复盘报告的接口响应结构。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_id: int
    version: int
    overall_metrics: dict[str, Any] | None
    strategy_evaluation: dict[str, Any] | None
    intervention_evaluation: dict[str, Any] | None
    reusable_conclusion: str | None
    lessons: str | None
    improvement: str | None
    generated_at: datetime


class ReviewCaseCandidate(BaseModel):
    """复盘中可沉淀到案例库的一条结构化案例。"""

    case_type: ReviewCaseType
    scene_desc: str = Field(
        min_length=1,
        max_length=2000,
    )
    anomaly_type: str | None = Field(
        default=None,
        max_length=32,
    )
    cause: str | None = Field(
        default=None,
        max_length=128,
    )
    action: str | None = Field(
        default=None,
        max_length=128,
    )
    effectiveness: CaseEffectiveness
    conclusion: str = Field(
        min_length=1,
        max_length=2000,
    )


class ReviewGenerationOutput(BaseModel):
    """大模型基于确定性复盘事实生成的叙事结论和案例。"""

    reusable_conclusion: str = Field(
        min_length=1,
        max_length=4000,
    )
    lessons: str = Field(
        min_length=1,
        max_length=4000,
    )
    improvement: str = Field(
        min_length=1,
        max_length=4000,
    )
    cases: list[ReviewCaseCandidate] = Field(
        min_length=1,
        max_length=6,
    )


class CaseLibraryRead(BaseModel):
    """案例库中一条可浏览的结构化投放案例。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    case_type: ReviewCaseType
    campaign_id: int | None
    scene_desc: str
    anomaly_type: str | None
    cause: str | None
    action: str | None
    effectiveness: CaseEffectiveness
    conclusion: str | None
    created_at: datetime

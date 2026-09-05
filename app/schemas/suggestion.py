from datetime import datetime
from typing import Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)


SuggestionActionType = Literal[
    "pause",
    "adjust_budget",
    "adjust_bid",
    "replace_creative",
    "narrow_audience",
    "switch_channel",
    "extend_observation",
    "manual_review",
]

SuggestionRiskLevel = Literal["低", "中", "高"]


class SuggestionCandidate(BaseModel):
    """大模型生成的一条候选干预建议。"""

    cause_id: int = Field(gt=0)
    action_type: SuggestionActionType
    action_params: dict[str, Any]
    metric_evidence: dict[str, Any] = Field(
        min_length=1,
    )
    triggered_rule: str = Field(
        min_length=1,
        max_length=128,
    )
    expected_impact: dict[str, Any] = Field(
        min_length=1,
    )
    risk_notes: str = Field(
        min_length=1,
        max_length=2000,
    )
    is_primary: bool


class SuggestionGenerationOutput(BaseModel):
    """大模型返回的主建议和备选建议集合。"""

    suggestions: list[SuggestionCandidate] = Field(
        min_length=2,
        max_length=5,
    )

    @model_validator(mode="after")
    def validate_primary_suggestion(self) -> Self:
        """验证建议集合中有且只有一条主建议。

        Returns:
            校验通过后的建议生成结果。

        Raises:
            ValueError: 主建议数量不是一条时抛出。
        """
        primary_count = sum(
            suggestion.is_primary
            for suggestion in self.suggestions
        )

        if primary_count != 1:
            raise ValueError("必须且只能包含一条主建议")

        return self


class InterventionSuggestionRead(BaseModel):
    """已经持久化的干预建议响应结构。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    anomaly_id: int
    campaign_id: int
    target_type: str
    target_id: int
    cause_id: int | None
    action_type: str
    action_params: dict[str, Any]
    metric_evidence: dict[str, Any] | None
    triggered_rule: str | None
    expected_impact: dict[str, Any] | None
    risk_notes: str | None
    risk_level: SuggestionRiskLevel
    is_primary: bool
    status: str
    created_at: datetime
    updated_at: datetime


class SuggestionGenerationResult(BaseModel):
    """生成建议接口的完整响应结构。"""

    anomaly_id: int
    data_sufficient: bool
    has_historical_cases: bool
    suggestions: list[InterventionSuggestionRead]
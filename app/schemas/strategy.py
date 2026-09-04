from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


StrategyStatus = Literal["待确认", "已确认", "已驳回"]

EvidenceType = Literal[
    "历史活动",
    "渠道规则",
    "产品卖点",
    "人群画像",
]


class ChannelChoice(BaseModel):
    channel_id: int = Field(gt=0)
    channel_name: str = Field(min_length=1)
    purpose: str = Field(min_length=1)


class AdGroupPlan(BaseModel):
    channel: str = Field(min_length=1)
    groups: list[str] = Field(min_length=1)


class StrategyPlan(BaseModel):
    channel_mix: list[ChannelChoice] = Field(min_length=1)
    budget_split: dict[str, Decimal] = Field(min_length=1)
    ad_group_structure: list[AdGroupPlan] = Field(min_length=1)
    audience_plan: dict[str, list[str]] = Field(min_length=1)
    keyword_plan: dict[str, list[str]] = Field(default_factory=dict)
    creative_test_plan: dict[str, str] = Field(min_length=1)
    bid_strategy: str = Field(min_length=1, max_length=64)
    expected_metrics: dict[str, Decimal] = Field(min_length=1)
    risk_notes: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_budget_channels(self) -> Self:
        """校验策略预算渠道。

        Returns:
            校验后的当前模型。
        """
        channel_names = {
            channel.channel_name
            for channel in self.channel_mix
        }

        if set(self.budget_split) != channel_names:
            raise ValueError("budget_split 必须覆盖全部投放渠道")

        if any(amount <= 0 for amount in self.budget_split.values()):
            raise ValueError("渠道预算必须大于 0")

        return self


class StrategyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_id: int
    version: int
    channel_mix: list[dict[str, Any]]
    budget_split: dict[str, Any]
    ad_group_structure: list[dict[str, Any]]
    audience_plan: dict[str, Any] | None
    keyword_plan: dict[str, Any] | None
    creative_test_plan: dict[str, Any] | None
    bid_strategy: str | None
    expected_metrics: dict[str, Any] | None
    risk_notes: str | None
    status: StrategyStatus
    confirmed_by: int | None
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class StrategyEvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    strategy_id: int
    evidence_type: EvidenceType
    target_item: str
    explanation: str
    source_ref: str | None
    vector_score: Decimal | None
    created_at: datetime


class StrategyDetail(BaseModel):
    strategy: StrategyRead
    evidence: list[StrategyEvidenceRead]

class StrategyConfirmResult(BaseModel):
    campaign_id: int
    strategy_id: int
    status: Literal["策略已确认"]

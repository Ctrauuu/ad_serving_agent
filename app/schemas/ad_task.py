from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class AdTaskCreateRequest(BaseModel):
    audience_id: int = Field(gt=0)
    creative_id: int = Field(gt=0)
    bid: Decimal = Field(
        gt=0,
        max_digits=10,
        decimal_places=2,
    )


class KeywordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ad_group_id: int
    word: str
    match_type: str
    bid: Decimal | None


class AdGroupTaskRead(BaseModel):
    id: int
    ad_plan_id: int
    campaign_id: int
    name: str
    audience_id: int | None
    creative_id: int | None
    bid: Decimal
    budget_daily: Decimal
    ad_platform_group_id: str | None
    status: str
    error_message: str | None
    keywords: list[KeywordRead]


class AdPlanTaskRead(BaseModel):
    id: int
    campaign_id: int
    strategy_id: int
    channel_id: int
    name: str
    budget_daily: Decimal
    budget_total: Decimal
    bid_strategy: str | None
    start_time: datetime | None
    end_time: datetime | None
    ad_platform_task_id: str | None
    status: str
    error_message: str | None
    groups: list[AdGroupTaskRead]


class AdTaskCreateResult(BaseModel):
    campaign_id: int
    status: str
    plans: list[AdPlanTaskRead]

class AdGroupStatusRead(BaseModel):
    id: int
    ad_platform_group_id: str | None
    status: str
    error_message: str | None

class AdTaskStatusResult(BaseModel):
    id: int
    campaign_id: int
    ad_platform_task_id: str | None
    status: str
    error_message: str | None
    groups: list[AdGroupStatusRead]
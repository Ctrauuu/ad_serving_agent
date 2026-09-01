
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Self
from pydantic import BaseModel, ConfigDict, Field, model_validator

CampaignStatus = Literal[
    "草稿",
    "目标已结构化",
    "策略生成中",
    "策略已确认",
    "任务创建中",
    "投放中",
    "已暂停",
    "已结束",
]
ConversionGoal = Literal["线索", "注册", "成交", "新品推广"]

class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    product_id: int = Field(gt=0)
    budget: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    start_date: date
    end_date: date
    conversion_goal: ConversionGoal
    goal_text: str = Field(min_length=1)
    risk_limit: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("结束日期不能早于开始日期")
        return self

class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    product_id: int | None = Field(default=None, gt=0)
    budget: Decimal | None = Field(
        default=None, gt=0, max_digits=12, decimal_places=2
    )
    start_date: date | None = None
    end_date: date | None = None
    conversion_goal: ConversionGoal | None = None
    goal_text: str | None = Field(default=None, min_length=1)
    risk_limit: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError("end_date 不能早于 start_date")
        return self

class CampaignRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    product_id: int
    owner_id: int
    budget: Decimal = Field(validation_alias="budget_total")
    start_date: date
    end_date: date
    conversion_goal: ConversionGoal
    goal_text: str | None
    structured_goal: dict[str, Any] | None
    risk_limit: str | None
    status: CampaignStatus
    created_at: datetime
    updated_at: datetime

class CampaignList(BaseModel):
    items: list[CampaignRead]
    total: int

class StructuredGoal(BaseModel):
    product: str = Field(min_length=1, description="推广产品")
    audience: str = Field(min_length=1, description="目标人群")
    budget: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    cycle: str = Field(min_length=1, description="投放周期")
    conversion_goal: ConversionGoal
    channels: list[str] = Field(min_length=1, description="投放渠道")
    risk: str = Field(min_length=1, description="风险限制")


class GoalParseResult(BaseModel):
    structured_goal: StructuredGoal | None = None
    missing_fields: list[str] = Field(default_factory=list)
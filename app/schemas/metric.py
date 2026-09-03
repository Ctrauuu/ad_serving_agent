from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class MetricSyncError(BaseModel):
    ad_group_id: int
    message: str


class MetricSyncResult(BaseModel):
    campaign_id: int
    status: Literal["success", "partial"]
    synced_groups: int
    failed_groups: int
    stale_groups: int
    metric_rows: int
    data_time: datetime
    errors: list[MetricSyncError]


MetricDimension = Literal[
    "campaign",
    "channel",
    "ad_group",
    "creative",
]


class RealtimeMetric(BaseModel):
    dimension: MetricDimension
    dim_id: int
    time_window: Literal["minute"]
    window_start: datetime
    impression: int
    click: int
    cost: Decimal
    lead: int
    valid_lead: int
    order: int
    ctr: Decimal | None
    cpc: Decimal | None
    cpa: Decimal | None
    roi: Decimal | None
    collected_at: datetime
    is_stale: bool


class RealtimeMetricResult(BaseModel):
    campaign_id: int
    dimension: MetricDimension
    data_time: datetime | None
    is_stale: bool
    items: list[RealtimeMetric]



MetricTrendWindow = Literal[
    "minute",
    "hour",
    "day",
]


class MetricTrendPoint(BaseModel):
    window_start: datetime
    impression: int
    click: int
    cost: Decimal
    lead: int
    valid_lead: int
    order: int
    ctr: Decimal | None
    cpc: Decimal | None
    cpa: Decimal | None
    roi: Decimal | None


class MetricTrendSeries(BaseModel):
    dim_id: int
    points: list[MetricTrendPoint]


class MetricTrendResult(BaseModel):
    campaign_id: int
    dimension: MetricDimension
    window: MetricTrendWindow
    data_time: datetime | None
    is_stale: bool
    series: list[MetricTrendSeries]

BudgetTargetType = Literal[
    "campaign",
    "ad_plan",
    "ad_group",
]


class BudgetConsumptionRead(BaseModel):
    target_type: BudgetTargetType
    target_id: int
    budget_total: Decimal
    cost_total: Decimal
    cost_rate: Decimal | None
    remaining: Decimal | None
    alert_status: str


class CampaignBudgetResult(BaseModel):
    campaign_id: int
    data_time: datetime | None
    is_stale: bool
    items: list[BudgetConsumptionRead]
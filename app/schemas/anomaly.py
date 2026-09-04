from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class MonitorRuleRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True
    )

    id: int
    name: str
    rule_type: str
    metric: str
    condition_json: dict[str, Any]
    stage: str
    channel_scope: str | None
    risk_level: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class AnomalyScanError(BaseModel):
    rule_id: int
    target_id: int
    message: str


class AnomalyScanResult(BaseModel):
    campaign_id: int
    status: Literal["completed", "partial"]
    stage: str
    scanned_groups: int
    evaluated_rules: int
    created_count: int
    deduplicated_count: int
    skipped_stale_groups: int
    skipped_no_data_groups: int
    created_ids: list[int]
    errors: list[AnomalyScanError]


AnomalyStatus = Literal[
    "待归因",
    "已归因",
    "已处理",
]


class AnomalyRecordRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True
    )

    id: int
    campaign_id: int
    target_type: str
    target_id: int
    anomaly_type: str
    metric: str
    metric_value: Decimal | None
    baseline_value: Decimal | None
    rule_id: int | None
    severity: str
    evidence_json: dict[str, Any] | None
    status: AnomalyStatus
    detected_at: datetime
    updated_at: datetime
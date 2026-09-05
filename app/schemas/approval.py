from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.suggestion import (
    InterventionSuggestionRead,
    SuggestionRiskLevel,
)

ApprovalStatus = Literal[
    "待审批",
    "已通过",
    "已驳回",
    "已超时",
]

ApprovalRoute = Literal[
    "auto_execute",
    "requires_approval",
    "forbidden",
]


class ApprovalRecordRead(BaseModel):
    """审批记录的查询响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    suggestion_id: int
    campaign_id: int
    risk_level: SuggestionRiskLevel
    auto_execute: bool
    approver_id: int | None
    approval_opinion: str | None
    reject_reason: str | None
    status: ApprovalStatus
    approved_at: datetime | None
    submitted_at: datetime


class ApprovalDetail(BaseModel):
    """审批记录及其关联干预建议。"""

    approval: ApprovalRecordRead
    suggestion: InterventionSuggestionRead


class ApprovalDecisionRequest(BaseModel):
    """负责人通过审批时提交的意见。"""

    opinion: str | None = Field(
        default=None,
        max_length=2000,
    )


class ApprovalRejectRequest(BaseModel):
    """负责人驳回审批时提交的原因。"""

    reason: str = Field(
        min_length=1,
        max_length=512,
    )

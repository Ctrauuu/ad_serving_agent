from datetime import datetime

import pytest
from pydantic import ValidationError

from app.models import ApprovalRecord
from app.schemas import ApprovalRecordRead, ApprovalRejectRequest


def test_approval_read_validates_orm_record() -> None:
    """验证审批 ORM 记录可以转换为响应 Schema。"""
    record = ApprovalRecord(
        id=4,
        suggestion_id=4,
        campaign_id=8,
        risk_level="低",
        auto_execute=True,
        status="已通过",
        approval_opinion="低风险自动执行",
        approved_at=datetime(2026, 9, 5, 12),
        submitted_at=datetime(2026, 9, 5, 12),
    )

    result = ApprovalRecordRead.model_validate(record)

    assert result.auto_execute is True
    assert result.status == "已通过"


def test_reject_reason_is_required() -> None:
    """验证驳回原因不能为空且不能超过数据库长度。"""
    with pytest.raises(ValidationError):
        ApprovalRejectRequest(reason="")

    with pytest.raises(ValidationError):
        ApprovalRejectRequest(reason="x" * 513)

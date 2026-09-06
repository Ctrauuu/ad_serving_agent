from datetime import datetime

import pytest
from pydantic import ValidationError

from app.models import ActionExecution
from app.schemas import ActionExecutionRead


def make_action_execution() -> ActionExecution:
    """构造动作执行响应测试使用的 ORM 记录。

    Returns:
        字段完整的成功执行记录。
    """
    return ActionExecution(
        id=4,
        approval_id=4,
        suggestion_id=4,
        campaign_id=8,
        target_type="ad_group",
        target_id=32,
        action_type="pause",
        action_params={"ad_group_id": 32},
        before_state={"status": "已上线"},
        after_state={"status": "已暂停"},
        tool_name="pause_ad_group",
        tool_result={"status": "已暂停"},
        executor_id=3,
        status="成功",
        error_message=None,
        rollback_status="可回滚",
        executed_at=datetime(2026, 9, 6, 13),
        created_at=datetime(2026, 9, 6, 13),
    )


def test_action_execution_read_validates_orm_record() -> None:
    """验证执行记录 ORM 可以转换为接口响应。"""
    result = ActionExecutionRead.model_validate(
        make_action_execution()
    )

    assert result.status == "成功"
    assert result.rollback_status == "可回滚"
    assert result.before_state == {"status": "已上线"}


def test_action_execution_read_rejects_unknown_status() -> None:
    """验证响应结构拒绝未定义的执行状态。"""
    action = make_action_execution()
    action.status = "处理中"

    with pytest.raises(ValidationError):
        ActionExecutionRead.model_validate(action)

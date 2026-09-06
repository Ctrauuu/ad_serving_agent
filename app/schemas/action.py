from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


ActionExecutionStatus = Literal[
    "待执行",
    "执行中",
    "成功",
    "失败",
]

ActionRollbackStatus = Literal[
    "不适用",
    "可回滚",
    "回滚中",
    "已回滚",
    "回滚失败",
    "需人工处理",
]


class ActionExecutionRead(BaseModel):
    """动作执行记录的接口响应结构。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    approval_id: int | None
    suggestion_id: int
    campaign_id: int
    target_type: str
    target_id: int
    action_type: str
    action_params: dict[str, Any]
    before_state: dict[str, Any] | None
    after_state: dict[str, Any] | None
    tool_name: str | None
    tool_result: dict[str, Any] | None
    executor_id: int | None
    status: ActionExecutionStatus
    error_message: str | None
    rollback_status: ActionRollbackStatus
    executed_at: datetime | None
    created_at: datetime

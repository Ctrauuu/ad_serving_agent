from app.models import ActionExecution


def test_action_execution_matches_existing_table() -> None:
    """验证动作执行模型映射到既有数据库表。"""
    assert ActionExecution.__tablename__ == "action_execution"
    assert set(ActionExecution.__table__.columns.keys()) == {
        "id",
        "approval_id",
        "suggestion_id",
        "campaign_id",
        "target_type",
        "target_id",
        "action_type",
        "action_params",
        "before_state",
        "after_state",
        "tool_name",
        "tool_result",
        "executor_id",
        "status",
        "error_message",
        "rollback_status",
        "executed_at",
        "created_at",
    }
    assert {
        index.name
        for index in ActionExecution.__table__.indexes
    } == {
        "idx_campaign",
        "idx_suggestion",
        "idx_status",
    }
    assert ActionExecution.__table__.c.status.server_default is not None
    assert (
        ActionExecution.__table__.c.rollback_status.server_default
        is not None
    )

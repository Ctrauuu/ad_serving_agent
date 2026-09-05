from app.models import (
    AnomalyCause,
    AnomalyRecord,
    ApprovalRecord,
    CaseLibrary,
    InterventionSuggestion,
    MonitorRule,
    SalesFeedback,
)


def test_anomaly_models_match_existing_tables() -> None:
    """验证异常识别模型映射到既有数据库表。"""
    assert MonitorRule.__tablename__ == "monitor_rule"
    assert AnomalyRecord.__tablename__ == "anomaly_record"
    assert {
        index.name
        for index in AnomalyRecord.__table__.indexes
    } == {
        "idx_campaign_status",
        "idx_target",
    }
    assert MonitorRule.__table__.c.enabled.server_default is not None
    assert AnomalyRecord.__table__.c.status.server_default is not None


def test_cause_models_match_existing_tables() -> None:
    """验证归因模型映射到既有数据库表和索引。"""
    assert AnomalyCause.__tablename__ == "anomaly_cause"
    assert SalesFeedback.__tablename__ == "sales_feedback"
    assert CaseLibrary.__tablename__ == "case_library"
    assert {
        index.name
        for index in AnomalyCause.__table__.indexes
    } == {"idx_anomaly"}
    assert {
        index.name
        for index in SalesFeedback.__table__.indexes
    } == {"idx_campaign", "idx_group"}
    assert {
        index.name
        for index in CaseLibrary.__table__.indexes
    } == {"idx_effectiveness", "idx_type"}


def test_suggestion_model_matches_existing_table() -> None:
    """验证干预建议模型映射到既有数据库表和索引。"""
    assert (
        InterventionSuggestion.__tablename__
        == "intervention_suggestion"
    )
    assert {
        index.name
        for index in InterventionSuggestion.__table__.indexes
    } == {"idx_anomaly", "idx_campaign_status"}
    assert (
        InterventionSuggestion.__table__.c.risk_level.server_default
        is not None
    )
    assert (
        InterventionSuggestion.__table__.c.is_primary.server_default
        is not None
    )
    assert (
        InterventionSuggestion.__table__.c.status.server_default
        is not None
    )


def test_approval_model_matches_existing_table() -> None:
    """验证审批记录模型映射到既有数据库表和索引。"""
    assert ApprovalRecord.__tablename__ == "approval_record"
    assert {
        index.name
        for index in ApprovalRecord.__table__.indexes
    } == {"idx_status", "idx_approver"}
    assert (
        ApprovalRecord.__table__.c.auto_execute.server_default
        is not None
    )
    assert (
        ApprovalRecord.__table__.c.status.server_default
        is not None
    )

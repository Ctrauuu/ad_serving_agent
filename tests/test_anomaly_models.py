from app.models import (
    AnomalyCause,
    AnomalyRecord,
    CaseLibrary,
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

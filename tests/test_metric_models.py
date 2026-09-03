from app.models import AdMetricRealtime, BudgetConsumption


def test_metric_models_match_existing_tables() -> None:
    assert AdMetricRealtime.__tablename__ == (
        "ad_metric_realtime"
    )
    assert BudgetConsumption.__tablename__ == (
        "budget_consumption"
    )
    assert (
        AdMetricRealtime.__table__.c.collected_at.server_default
        is not None
    )
    assert (
        BudgetConsumption.__table__.c.alert_status.server_default
        is not None
    )

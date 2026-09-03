from app.models import AdGroup, AdPlan, Keyword


def test_ad_task_models_match_existing_tables() -> None:
    assert AdPlan.__tablename__ == "ad_plan"
    assert AdGroup.__tablename__ == "ad_group"
    assert Keyword.__tablename__ == "keyword"

    assert AdPlan.__table__.c.status.server_default is not None
    assert AdGroup.__table__.c.status.server_default is not None
    assert Keyword.__table__.c.match_type.server_default is not None

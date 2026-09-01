from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError
from app.schemas.campaign import CampaignCreate, StructuredGoal



def test_campaign_dates_must_be_ordered() -> None:
    with pytest.raises(ValidationError):
        CampaignCreate(
            name="新品推广",
            product_id=1,
            budget=Decimal("80000.00"),
            start_date=date(2026, 9, 30),
            end_date=date(2026, 9, 1),
            conversion_goal="线索",
            goal_text="预算8万获取高质量线索",
        )

def test_structured_goal_reports_missing_fields() -> None:
    with pytest.raises(ValidationError) as exc_info:
        StructuredGoal(
            product="企业培训产品",
            budget=Decimal("80000.00"),
            conversion_goal="线索",
            channels=["信息流"],
        )

    missing = {
        error["loc"][0]
        for error in exc_info.value.errors()
        if error["type"] == "missing"
    }
    assert missing == {"audience", "cycle", "risk"}
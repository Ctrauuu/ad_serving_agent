from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas import StrategyPlan


def test_strategy_plan_requires_budget_for_every_channel() -> None:
    with pytest.raises(
        ValidationError,
        match="budget_split 必须覆盖全部投放渠道",
    ):
        StrategyPlan(
            channel_mix=[
                {
                    "channel_id": 1,
                    "channel_name": "信息流",
                    "purpose": "扩大线索覆盖",
                },
                {
                    "channel_id": 2,
                    "channel_name": "搜索广告",
                    "purpose": "承接主动搜索需求",
                },
            ],
            budget_split={
                "信息流": Decimal("50000"),
            },
            ad_group_structure=[
                {
                    "channel": "信息流",
                    "groups": ["HR负责人", "企业管理者"],
                }
            ],
            audience_plan={
                "信息流": ["中小企业HR负责人"],
            },
            creative_test_plan={
                "信息流": "测试痛点型和效率型素材",
            },
            bid_strategy="按转化成本优化",
            expected_metrics={
                "cpa": Decimal("300"),
            },
            risk_notes="关注无效线索比例",
        )
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Campaign,
    Channel,
    Strategy,
    StrategyEvidence,
)
from app.schemas import StrategyPlan
from app.services.strategy import (
    _validate_strategy_plan,
    get_latest_strategy,
    confirm_strategy,
)


def test_strategy_budget_cannot_exceed_campaign_budget() -> None:
    channel = Channel(
        id=1,
        name="信息流",
    )

    plan = StrategyPlan(
        channel_mix=[
            {
                "channel_id": 1,
                "channel_name": "信息流",
                "purpose": "获取线索",
            }
        ],
        budget_split={
            "信息流": Decimal("90000"),
        },
        ad_group_structure=[
            {
                "channel": "信息流",
                "groups": ["HR负责人"],
            }
        ],
        audience_plan={
            "信息流": ["中小企业HR负责人"],
        },
        creative_test_plan={
            "信息流": "测试痛点型素材",
        },
        bid_strategy="按转化成本优化",
        expected_metrics={
            "cpa": Decimal("300"),
        },
        risk_notes="关注无效线索比例",
    )

    with pytest.raises(
        ValueError,
        match="超过活动预算",
    ):
        _validate_strategy_plan(
            plan=plan,
            budget_limit=Decimal("80000"),
            channels_by_id={
                1: channel,
            },
        )


@pytest.mark.asyncio
async def test_get_latest_strategy_returns_evidence() -> None:
    session = AsyncMock(spec=AsyncSession)

    strategy = Strategy(
        id=21,
        campaign_id=8,
        version=2,
        channel_mix=[],
        budget_split={},
        ad_group_structure=[],
        audience_plan={},
        keyword_plan={},
        creative_test_plan={},
        bid_strategy="按转化成本优化",
        expected_metrics={},
        risk_notes="关注线索质量",
        status="待确认",
        confirmed_by=None,
        confirmed_at=None,
        created_at=datetime(2026, 9, 2),
        updated_at=datetime(2026, 9, 2),
    )
    session.scalar.return_value = strategy

    evidence = StrategyEvidence(
        id=31,
        strategy_id=21,
        evidence_type="渠道规则",
        target_item="信息流",
        explanation="信息流适合线索获取",
        source_ref="channel:1",
        vector_score=None,
        created_at=datetime(2026, 9, 2),
    )

    rows = MagicMock()
    rows.all.return_value = [evidence]
    session.scalars.return_value = rows

    result = await get_latest_strategy(
        session,
        campaign_id=8,
    )

    assert result is not None
    assert result.strategy.id == 21
    assert result.strategy.version == 2
    assert len(result.evidence) == 1
    assert (
        result.evidence[0].evidence_type
        == "渠道规则"
    )

    strategy_statement = (
        session.scalar.await_args.args[0]
    )
    assert "strategy.version DESC" in str(
        strategy_statement
    )

@pytest.mark.asyncio
async def test_confirm_strategy_updates_status_and_vector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock(spec=AsyncSession)

    campaign = Campaign(
        id=8,
        status="策略生成中",
        structured_goal={
            "product": "企业HR系统",
            "audience": "企业HR负责人",
            "budget": 80000,
            "cycle": "2026年9月",
            "conversion_goal": "线索",
            "channels": ["信息流"],
            "risk": "单条线索成本不超过300元",
        },
    )

    strategy = Strategy(
        id=21,
        campaign_id=8,
        version=1,
        status="待确认",
    )
    session.scalar.return_value = strategy

    captured: dict[str, object] = {}

    async def fake_embed_goal(
        goal,
        text_type,
    ):
        captured["text_type"] = text_type
        return [0.1] * 1024

    async def fake_upsert_strategy_vector(
        strategy_id,
        campaign_id,
        goal_vector,
    ):
        captured["strategy_id"] = strategy_id
        captured["campaign_id"] = campaign_id
        captured["vector_length"] = len(
            goal_vector
        )

    monkeypatch.setattr(
        "app.services.strategy.embed_goal",
        fake_embed_goal,
    )
    monkeypatch.setattr(
        (
            "app.services.strategy.milvus_client."
            "upsert_strategy_vector"
        ),
        fake_upsert_strategy_vector,
    )

    result = await confirm_strategy(
        session=session,
        campaign=campaign,
        confirmed_by=3,
    )

    assert result.status == "策略已确认"
    assert strategy.status == "已确认"
    assert strategy.confirmed_by == 3
    assert strategy.confirmed_at is not None
    assert campaign.status == "策略已确认"

    assert captured["text_type"] == "document"
    assert captured["strategy_id"] == 21
    assert captured["campaign_id"] == 8
    assert captured["vector_length"] == 1024

    session.commit.assert_awaited_once()
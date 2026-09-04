import json
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AdGroup,
    AdMetricRealtime,
    AdPlan,
    AnomalyRecord,
    Audience,
    Channel,
    Creative,
    SalesFeedback,
)
from app.services.cause import collect_attribution_signals


def make_anomaly(
    target_type: str = "ad_group",
) -> AnomalyRecord:
    """创建归因信号测试异常。

    Args:
        target_type: 异常目标类型。

    Returns:
        测试异常记录。
    """
    return AnomalyRecord(
        id=7,
        campaign_id=8,
        target_type=target_type,
        target_id=31,
        anomaly_type="valid_lead_drop",
        metric="valid_lead_rate",
        metric_value=Decimal("0.1000"),
        baseline_value=Decimal("0.2700"),
        severity="高",
        evidence_json={"stage": "稳态期"},
        status="待归因",
        detected_at=datetime(2026, 9, 4, 12, 0),
    )


def make_session(
    feedbacks: list[SalesFeedback],
    *,
    include_creative: bool = True,
) -> AsyncMock:
    """创建包含广告信号的模拟数据库会话。

    Args:
        feedbacks: 销售反馈列表。
        include_creative: 是否提供素材。

    Returns:
        配置完成的异步数据库会话替身。
    """
    session = AsyncMock(spec=AsyncSession)
    group = AdGroup(
        id=31,
        campaign_id=8,
        ad_plan_id=21,
        audience_id=1,
        creative_id=1 if include_creative else None,
        name="测试广告组",
        bid=Decimal("30"),
        budget_daily=Decimal("1000"),
        status="已上线",
    )
    objects = {
        AdGroup: group,
        AdPlan: AdPlan(id=21, channel_id=1),
        Channel: Channel(
            id=1,
            name="信息流",
            platform="mock",
            rules="按转化出价",
        ),
        Audience: Audience(
            id=1,
            name="HR负责人",
        ),
        Creative: (
            Creative(
                id=1,
                name="痛点视频",
                type="视频",
                version=1,
                status="已审核",
                created_at=datetime(2026, 8, 10),
            )
            if include_creative
            else None
        ),
    }

    async def fake_get(
        model: type[object],
        object_id: int,
    ) -> object | None:
        """按模型返回对应测试对象。"""
        return objects.get(model)

    session.get.side_effect = fake_get
    session.scalar.return_value = AdMetricRealtime(
        campaign_id=8,
        dimension="ad_group",
        dim_id=31,
        time_window="hour",
        window_start=datetime(2026, 9, 4, 11),
        impression=1000,
        click=60,
        cost=Decimal("1300"),
        lead=10,
        valid_lead=1,
        order=0,
        ctr=None,
        cpc=None,
        cpa=Decimal("130"),
        roi=None,
        collected_at=datetime(2026, 9, 4, 12),
    )
    result = MagicMock()
    result.all.return_value = feedbacks
    session.scalars.return_value = result
    return session


@pytest.mark.asyncio
async def test_collect_signals_marks_recent_feedback_sufficient() -> None:
    """验证三条近期反馈会被标记为数据充分。"""
    anomaly = make_anomaly()
    feedbacks = [
        SalesFeedback(
            campaign_id=8,
            ad_group_id=31,
            lead_id=f"lead_{index}",
            lead_quality="有效" if index == 0 else "无效",
            feedback_at=anomaly.detected_at - timedelta(hours=index),
        )
        for index in range(3)
    ]

    signals, sufficient = await collect_attribution_signals(
        make_session(feedbacks),
        anomaly,
    )

    assert sufficient is True
    assert signals["sales_feedback"]["recent_count"] == 3
    assert "lead_id" not in json.dumps(signals, ensure_ascii=False)
    assert signals["creative"]["running_days"] == 25
    assert signals["metric_snapshot"]["ctr"] is None


@pytest.mark.asyncio
async def test_collect_signals_handles_missing_feedback_and_creative() -> None:
    """验证缺少反馈和素材时返回不足而非报错。"""
    signals, sufficient = await collect_attribution_signals(
        make_session([], include_creative=False),
        make_anomaly(),
    )

    assert sufficient is False
    assert signals["creative"] is None
    assert signals["landing_page"] is None


@pytest.mark.asyncio
async def test_collect_signals_rejects_unsupported_target() -> None:
    """验证当前只接受广告组级异常。"""
    with pytest.raises(ValueError, match="暂不支持"):
        await collect_attribution_signals(
            AsyncMock(spec=AsyncSession),
            make_anomaly("campaign"),
        )

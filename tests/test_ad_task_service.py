from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AdGroup,
    AdPlan,
    Audience,
    Campaign,
    Channel,
    Creative,
    Keyword,
    Strategy,
)
from app.schemas import (
    AdTaskCreateRequest,
    AdTaskCreateResult,
    StrategyPlan,
)
from app.services.ad_task import (
    _create_local_tasks,
    create_ad_tasks,
    list_ad_groups,
    sync_ad_task_status,
)


def make_strategy_plan() -> StrategyPlan:
    return StrategyPlan(
        channel_mix=[
            {
                "channel_id": 1,
                "channel_name": "信息流",
                "purpose": "获取线索",
            }
        ],
        budget_split={"信息流": Decimal("3000")},
        ad_group_structure=[
            {
                "channel": "信息流",
                "groups": ["老板人群", "财务人群"],
            }
        ],
        audience_plan={"信息流": ["中小企业"]},
        keyword_plan={"信息流": ["财税软件", "企业报税"]},
        creative_test_plan={"信息流": "痛点素材"},
        bid_strategy="按转化成本优化",
        expected_metrics={"cpa": Decimal("100")},
        risk_notes="控制线索成本",
    )


@pytest.mark.asyncio
async def test_create_local_tasks_splits_strategy_first() -> None:
    class FakeSession:
        def __init__(self) -> None:
            self.added: list[object] = []
            self.next_id = 1
            self.commits = 0

        def add(self, value) -> None:
            value.id = self.next_id
            self.next_id += 1
            self.added.append(value)

        async def flush(self) -> None:
            return None

        async def commit(self) -> None:
            self.commits += 1

    session = FakeSession()
    campaign = Campaign(
        id=8,
        name="财税推广",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
        status="策略已确认",
    )
    strategy = Strategy(id=21)
    form = AdTaskCreateRequest(
        audience_id=1,
        creative_id=1,
        bid=Decimal("5"),
    )

    plans = await _create_local_tasks(
        session=session,  # type: ignore[arg-type]
        campaign=campaign,
        strategy=strategy,
        strategy_plan=make_strategy_plan(),
        form=form,
    )

    assert len(plans) == 1
    assert len([x for x in session.added if isinstance(x, AdPlan)]) == 1
    assert len([x for x in session.added if isinstance(x, AdGroup)]) == 2
    assert len([x for x in session.added if isinstance(x, Keyword)]) == 4
    assert campaign.status == "任务创建中"
    assert session.commits == 1


@pytest.mark.asyncio
async def test_create_ad_tasks_continues_after_group_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock(spec=AsyncSession)
    campaign = Campaign(
        id=8,
        name="财税推广",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
        status="策略已确认",
    )
    plan_data = make_strategy_plan()
    strategy = Strategy(
        id=21,
        campaign_id=8,
        status="已确认",
        **plan_data.model_dump(),
    )
    audience = Audience(id=1, status="启用")
    creative = Creative(id=1, status="已审核")
    channel = Channel(id=1, name="信息流", status="启用")
    plan = AdPlan(
        id=31,
        campaign_id=8,
        strategy_id=21,
        channel_id=1,
        name="信息流计划",
        budget_daily=Decimal("100"),
        budget_total=Decimal("3000"),
        ad_platform_task_id="mock_plan_1",
        status="已上线",
    )
    failed_group = AdGroup(
        id=41,
        ad_plan_id=31,
        campaign_id=8,
        name="老板人群",
        audience_id=1,
        creative_id=1,
        bid=Decimal("5"),
        budget_daily=Decimal("50"),
        status="待创建",
    )
    online_group = AdGroup(
        id=42,
        ad_plan_id=31,
        campaign_id=8,
        name="财务人群",
        audience_id=1,
        creative_id=1,
        bid=Decimal("5"),
        budget_daily=Decimal("50"),
        status="待创建",
    )

    session.scalar.return_value = strategy

    async def fake_get(model, _):
        return audience if model is Audience else creative

    session.get.side_effect = fake_get

    def rows(values):
        result = MagicMock()
        result.all.return_value = values
        return result

    session.scalars.side_effect = [
        rows([channel]),
        rows([plan]),
        rows([failed_group, online_group]),
    ]

    calls: list[tuple[str, dict]] = []

    async def fake_call(tool_name, arguments):
        calls.append((tool_name, arguments))
        if (
            tool_name == "create_ad_group"
            and arguments["name"] == "老板人群"
        ):
            raise RuntimeError("平台创建失败")
        if tool_name == "create_ad_group":
            return {
                "ad_platform_group_id": "mock_group_42",
                "status": "审核中",
            }
        return {"status": "已上线"}

    async def fake_list_ad_tasks(session, campaign):
        return AdTaskCreateResult(
            campaign_id=campaign.id,
            status=campaign.status,
            plans=[],
        )

    monkeypatch.setattr(
        "app.services.ad_task.call_ad_platform_tool",
        fake_call,
    )
    monkeypatch.setattr(
        "app.services.ad_task.list_ad_tasks",
        fake_list_ad_tasks,
    )

    result = await create_ad_tasks(
        session,
        campaign,
        AdTaskCreateRequest(
            audience_id=1,
            creative_id=1,
            bid=Decimal("5"),
        ),
    )

    assert failed_group.status == "创建失败"
    assert online_group.status == "已上线"
    assert online_group.ad_platform_group_id == "mock_group_42"
    assert campaign.status == "任务创建中"
    assert result.status == "任务创建中"
    assert [
        args["name"]
        for tool, args in calls
        if tool == "create_ad_group"
    ] == ["老板人群", "财务人群"]


@pytest.mark.asyncio
async def test_sync_status_keeps_other_groups_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock(spec=AsyncSession)
    campaign = Campaign(id=8, status="任务创建中")
    plan = AdPlan(
        id=31,
        campaign_id=8,
        ad_platform_task_id="mock_plan_31",
        status="审核中",
    )
    online_group = AdGroup(
        id=41,
        ad_plan_id=31,
        campaign_id=8,
        ad_platform_group_id="mock_group_41",
        status="审核中",
    )
    failed_group = AdGroup(
        id=42,
        ad_plan_id=31,
        campaign_id=8,
        ad_platform_group_id="mock_group_42",
        status="审核中",
    )

    def rows(values):
        result = MagicMock()
        result.all.return_value = values
        return result

    session.scalars.side_effect = [
        rows([online_group, failed_group]),
        rows([plan]),
        rows([online_group, failed_group]),
    ]

    async def fake_call(_, arguments):
        if arguments["platform_id"] == "mock_group_42":
            raise RuntimeError("平台暂时不可用")
        return {"status": "已上线"}

    monkeypatch.setattr(
        "app.services.ad_task.call_ad_platform_tool",
        fake_call,
    )

    result = await sync_ad_task_status(
        session,
        campaign,
        plan,
    )

    assert plan.status == "已上线"
    assert online_group.status == "已上线"
    assert failed_group.status == "审核中"
    assert "平台暂时不可用" in failed_group.error_message
    assert campaign.status == "任务创建中"
    assert result.groups[0].status == "已上线"
    assert result.groups[1].error_message is not None
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_ad_groups_flattens_task_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = SimpleNamespace(id=1)
    second = SimpleNamespace(id=2)

    async def fake_list_ad_tasks(session, campaign):
        return SimpleNamespace(
            plans=[
                SimpleNamespace(groups=[first]),
                SimpleNamespace(groups=[second]),
            ]
        )

    monkeypatch.setattr(
        "app.services.ad_task.list_ad_tasks",
        fake_list_ad_tasks,
    )

    result = await list_ad_groups(
        AsyncMock(spec=AsyncSession),
        Campaign(id=8),
    )

    assert result == [first, second]

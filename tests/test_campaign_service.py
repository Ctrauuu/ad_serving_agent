from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Campaign, User
from app.schemas import CampaignCreate, CampaignUpdate
from app.services.campaign import (
    create_campaign,
    get_campaign,
    list_campaigns,
    update_campaign,
)

from app.schemas import CampaignCreate, CampaignUpdate, StructuredGoal

@pytest.mark.asyncio
async def test_create_campaign_maps_and_persists_fields() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = 1

    form = CampaignCreate(
        name="新品推广",
        product_id=1,
        budget=Decimal("80000.00"),
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
        conversion_goal="线索",
        goal_text="预算8万获取高质量线索",
    )

    campaign = await create_campaign(session, form, owner_id=7)

    assert campaign is not None
    assert campaign.owner_id == 7
    assert campaign.budget_total == Decimal("80000.00")
    assert campaign.status == "草稿"
    session.add.assert_called_once_with(campaign)
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(campaign)


@pytest.mark.asyncio
async def test_non_leader_campaign_query_is_owner_scoped() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None
    user = User(id=7, role="投放人员")

    await get_campaign(session, campaign_id=5, current_user=user)

    statement = session.scalar.await_args.args[0]
    assert "campaign.owner_id" in str(statement)

@pytest.mark.asyncio
async def test_campaign_list_is_owner_scoped() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = 0

    rows = MagicMock()
    rows.all.return_value = []
    session.scalars.return_value = rows

    user = User(id=7, role="投放人员")

    items, total = await list_campaigns(
        session,
        current_user=user,
        page=1,
        page_size=20,
        keyword="新品",
    )

    count_statement = session.scalar.await_args.args[0]
    list_statement = session.scalars.await_args.args[0]

    assert items == []
    assert total == 0
    assert "campaign.owner_id" in str(count_statement)
    assert "campaign.owner_id" in str(list_statement)
    assert "campaign.name LIKE" in str(count_statement)


@pytest.mark.asyncio
async def test_update_checks_date_against_existing_campaign() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = Campaign(
        id=5,
        owner_id=7,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
    )
    user = User(id=7, role="投放人员")

    with pytest.raises(ValueError, match="结束日期"):
        await update_campaign(
            session,
            campaign_id=5,
            form=CampaignUpdate(start_date=date(2026, 10, 1)), # type: ignore
            current_user=user,
        )

    session.commit.assert_not_awaited()

@pytest.mark.asyncio
async def test_confirm_goal_saves_json_and_changes_status() -> None:
    session = AsyncMock(spec=AsyncSession)
    campaign = Campaign(
        id=5,
        owner_id=7,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
        status="草稿",
    )
    session.scalar.return_value = campaign
    user = User(id=7, role="投放人员")

    result = await update_campaign(
        session,
        campaign_id=5,
        form=CampaignUpdate(
            structured_goal=StructuredGoal(
                product="企业HR系统",
                audience="企业HR负责人",
                budget=Decimal("80000.00"),
                cycle="2026年9月",
                conversion_goal="线索",
                channels=["信息流"],
                risk="单条线索成本不超过300元",
            )
        ),
        current_user=user,
    )

    assert result is campaign
    assert campaign.status == "目标已结构化"
    assert campaign.structured_goal["product"] == "企业HR系统" # type: ignore
    assert campaign.structured_goal["budget"] == 80000.0# type: ignore
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(campaign)

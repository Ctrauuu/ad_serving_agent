from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.schemas import CampaignCreate
from app.services.campaign import create_campaign, get_campaign


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
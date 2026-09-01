from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas import CampaignCreate
from app.models import Campaign, Product, User

async def create_campaign(
    session:AsyncSession,
    form:CampaignCreate,
    owner_id:int
) -> Campaign | None:
    product_id = await session.scalar(
        select(Product.id).where(
            Product.id == form.product_id,
            Product.status == "启用"
        )
    )

    if not product_id:
        return None

    campaign = Campaign(
        name=form.name,
        product_id=form.product_id,
        owner_id=owner_id,
        budget_total=form.budget,
        start_date=form.start_date,
        end_date=form.end_date,
        conversion_goal=form.conversion_goal,
        goal_text=form.goal_text,
        risk_limit=form.risk_limit,
        status="草稿",
    )

    session.add(campaign)
    await session.commit()
    await session.refresh(campaign)
    return campaign

async def get_campaign(
    session:AsyncSession,
    campaign_id:int,
    current_user:User
) -> Campaign | None:
    filters=[Campaign.id == campaign_id]
    # ponytail: owner_id 是当前唯一参与关系；需要运营人员范围时增加 campaign_member 表。
    if current_user.role != "投放负责人":
        filters.append(Campaign.owner_id == current_user.id)

    return await session.scalar(select(Campaign).where(*filters))
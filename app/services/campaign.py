from sqlalchemy import select,func
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas import CampaignCreate,CampaignStatus,CampaignUpdate
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

async def list_campaigns(
    session:AsyncSession,
    current_user:User,
    page:int,
    page_size:int,
    status:CampaignStatus | None = None,
    keyword: str | None = None,
) -> tuple[list[Campaign], int]:
    filters=[]

    if current_user.role != "投放负责人":
        filters.append(Campaign.owner_id == current_user.id)

    if status:
        filters.append(Campaign.status==status)
    if keyword and keyword.strip():
        filters.append(Campaign.name.like(f"%{keyword.strip()}%"))

    total = await session.scalar(
        select(func.count()).select_from(Campaign).where(*filters)
    ) or 0

    campaigns = await session.scalars(
        select(Campaign)
        .where(*filters)
        .order_by(Campaign.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    return list(campaigns.all()), total


async def update_campaign(
    session: AsyncSession,
    campaign_id: int,
    form: CampaignUpdate,
    current_user: User,
) -> Campaign | None:
    campaign = await get_campaign(session, campaign_id, current_user)
    if campaign is None:
        return None

    confirming_goal = "structured_goal" in form.model_fields_set
    data = form.model_dump(exclude_unset=True)

    if not data:
        return campaign

    required_fields = {
        "name",
        "product_id",
        "budget",
        "start_date",
        "end_date",
        "conversion_goal",
        "structured_goal",
    }
    if any(data.get(field) is None for field in required_fields & data.keys()):
        raise ValueError("活动必填字段不能为 null")

    start_date = data.get("start_date", campaign.start_date)
    end_date = data.get("end_date", campaign.end_date)
    if end_date < start_date:
        raise ValueError("结束日期不能早于开始日期")

    if "product_id" in data:
        product_id = await session.scalar(
            select(Product.id).where(
                Product.id == data["product_id"],
                Product.status == "启用",
            )
        )
        if product_id is None:
            raise ValueError("指定的产品不存在或未启用")

    if confirming_goal and campaign.status not in {
        "草稿",
        "目标已结构化",
    }:
        raise ValueError("当前活动状态不允许确认结构化目标")

    if "budget" in data:
        campaign.budget_total = data.pop("budget")

    if confirming_goal:
        data.pop("structured_goal")
        goal = form.structured_goal
        assert goal is not None

        goal_data = goal.model_dump(mode="json")
        goal_data["budget"] = float(goal.budget)

        campaign.structured_goal = goal_data
        campaign.status = "目标已结构化"

    for field, value in data.items():
        setattr(campaign, field, value)

    await session.commit()
    await session.refresh(campaign)
    return campaign

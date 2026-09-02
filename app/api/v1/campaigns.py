from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Query,
    status,
)
from fastapi.responses import JSONResponse

from app.api.dependencies.auth import (
    CurrentUser,
    SessionDep,
    require_role,
)
from app.api.routing import UnifiedResponseRoute
from app.core.responses import error
from app.models import User
from app.schemas import (
    CampaignCreate,
    CampaignList,
    CampaignRead,
    CampaignStatus,
    CampaignUpdate,
    GoalParseResult,
    StrategyDetail,
    StrategyConfirmResult,
)
from app.services.campaign import (
    create_campaign,
    get_campaign,
    list_campaigns,
    update_campaign,
)
from app.services.goal import parse_goal_text
from app.services.strategy import (
    confirm_strategy,
    generate_strategy,
    get_latest_strategy,
)


CampaignCreator = Annotated[User,Depends(require_role("投放人员"))]
StrategyConfirmer = Annotated[
    User,
    Depends(require_role("投放负责人")),
]
CampaignId = Annotated[int,Path(gt=0)]

router = APIRouter(
    prefix="/campaigns",
    tags=["campaigns"],
    route_class=UnifiedResponseRoute,
)

@router.get("",response_model=None)
async def campaign_list(
    session: SessionDep,
    current_user: CurrentUser,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[
        CampaignStatus | None,
        Query(alias="status"),
    ] = None,
    keyword: Annotated[str | None, Query(max_length=128)] = None,
) -> CampaignList:
    campaigns, total = await list_campaigns(
        session,
        current_user=current_user,
        page=page,
        page_size=page_size,
        status=status_filter,
        keyword=keyword,
    )

    return CampaignList(
        items=[CampaignRead.model_validate(item) for item in campaigns],
        total=total,
    )

@router.post("",response_model=None,status_code=status.HTTP_201_CREATED)
async def campaign_create(
    form: CampaignCreate,
    session: SessionDep,
    current_user: CampaignCreator,
) -> CampaignRead:
    campaign = await create_campaign(session,form,current_user.id)

    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="产品不存在或未启用",
        )

    return CampaignRead.model_validate(campaign)

@router.get("/{campaign_id}",response_model=None)
async def campaign_detail(
    campaign_id: CampaignId,
    session: SessionDep,
    current_user: CurrentUser
) -> CampaignRead:
    campaign = await get_campaign(session, campaign_id, current_user)

    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="活动不存在",
        )

    return CampaignRead.model_validate(campaign)

@router.put("/{campaign_id}",response_model=None)
async def campaign_update(
    campaign_id: CampaignId,
    form: CampaignUpdate,
    session: SessionDep,
    current_user: CurrentUser
) -> CampaignRead:
    if (
        "structured_goal" in form.model_fields_set
        and current_user.role != "投放人员"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅投放人员可以确认结构化目标",
        )

    try:
        campaign = await update_campaign(
            session,
            campaign_id, 
            form, 
            current_user
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="活动不存在",
        )

    return CampaignRead.model_validate(campaign)

@router.post("/{campaign_id}/parse-goal",response_model=None)
async def campaign_parse_goal(
    campaign_id:CampaignId,
    session: SessionDep,
    current_user:CurrentUser,
) -> GoalParseResult | JSONResponse:
    campaign = await get_campaign(session, campaign_id, current_user)
    if campaign is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="活动不存在",
        )

    if not campaign.goal_text or not campaign.goal_text.strip():
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=error(
                422,
                "目标信息不完整",
                {"missing_fields": ["goal_text"]},
            ),
        )

    try:
        result = await parse_goal_text(campaign.goal_text)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    if result.missing_fields:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=error(
                422,
                "目标信息不完整",
                {"missing_fields": result.missing_fields},
            ),
        )

    return result


@router.post(
    "/{campaign_id}/strategy/generate",
    response_model=None,
)
async def campaign_generate_strategy(
    campaign_id: CampaignId,
    session: SessionDep,
    current_user: CurrentUser,
) -> StrategyDetail:
    campaign = await get_campaign(
        session,
        campaign_id,
        current_user,
    )

    if campaign is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="活动不存在",
        )

    try:
        return await generate_strategy(
            session,
            campaign,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_CONTENT
            ),
            detail=str(exc),
        ) from exc

@router.get(
    "/{campaign_id}/strategy",
    response_model=None,
)
async def campaign_strategy_detail(
    campaign_id: CampaignId,
    session: SessionDep,
    current_user: CurrentUser,
) -> StrategyDetail:
    campaign = await get_campaign(
        session,
        campaign_id,
        current_user,
    )

    if campaign is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="活动不存在",
        )

    result = await get_latest_strategy(
        session,
        campaign.id,
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="策略不存在",
        )

    return result

@router.post(
    "/{campaign_id}/strategy/confirm",
    response_model=None,
)
async def campaign_confirm_strategy(
    campaign_id: CampaignId,
    session: SessionDep,
    current_user: StrategyConfirmer,
) -> StrategyConfirmResult:
    campaign = await get_campaign(
        session,
        campaign_id,
        current_user,
    )

    if campaign is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="活动不存在",
        )

    try:
        return await confirm_strategy(
            session=session,
            campaign=campaign,
            confirmed_by=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_CONTENT
            ),
            detail=str(exc),
        ) from exc
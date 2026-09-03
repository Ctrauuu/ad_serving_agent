from typing import Annotated

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    status,
)

from app.api.dependencies.auth import (
    CurrentUser,
    SessionDep,
)
from app.api.routing import UnifiedResponseRoute
from app.schemas import AdGroupTaskRead
from app.services.ad_task import list_ad_groups
from app.services.campaign import get_campaign


CampaignQueryId = Annotated[
    int,
    Query(gt=0),
]

router = APIRouter(
    prefix="/ad-groups",
    tags=["ad-groups"],
    route_class=UnifiedResponseRoute,
)


@router.get(
    "",
    response_model=None,
)
async def ad_group_list(
    campaign_id: CampaignQueryId,
    session: SessionDep,
    current_user: CurrentUser,
) -> list[AdGroupTaskRead]:
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

    return await list_ad_groups(
        session,
        campaign,
    )
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies.auth import CurrentUser, SessionDep
from app.api.routing import UnifiedResponseRoute
from app.schemas import CaseLibraryRead, ReviewCaseType
from app.services.review import list_review_cases


router = APIRouter(
    prefix="/cases",
    tags=["cases"],
    route_class=UnifiedResponseRoute,
)


@router.get("", response_model=None)
async def case_list(
    session: SessionDep,
    current_user: CurrentUser,
    case_type: Annotated[
        ReviewCaseType | None,
        Query(),
    ] = None,
) -> list[CaseLibraryRead]:
    """查询当前用户可浏览的历史案例库。

    Args:
        session: 数据库异步会话。
        current_user: 当前已认证用户。
        case_type: 可选案例类型筛选条件。

    Returns:
        按创建时间倒序排列的案例列表。
    """
    cases = await list_review_cases(
        session,
        case_type,
    )

    return [
        CaseLibraryRead.model_validate(case)
        for case in cases
    ]

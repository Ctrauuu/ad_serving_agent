from typing import Annotated

from fastapi import (
    APIRouter,
    HTTPException,
    Path,
    status,
)

from app.api.dependencies.auth import (
    CurrentUser,
    SessionDep,
)
from app.api.routing import UnifiedResponseRoute
from app.models import AnomalyRecord
from app.schemas import (
    CauseAnalysisResult,
    SuggestionGenerationResult,
)
from app.services.campaign import get_campaign
from app.services.cause import (
    analyze_anomaly_cause,
    get_anomaly_cause_result,
)
from app.services.suggestion import (
    generate_intervention_suggestions,
    get_intervention_suggestion_result,
)

AnomalyId = Annotated[int, Path(gt=0)]

router = APIRouter(
    prefix="/anomalies",
    tags=["anomaly-causes"],
    route_class=UnifiedResponseRoute,
)


@router.post(
    "/{anomaly_id}/cause/analyze",
    response_model=None,
)
async def anomaly_cause_analyze(
    anomaly_id: AnomalyId,
    session: SessionDep,
    current_user: CurrentUser,
) -> CauseAnalysisResult:
    """触发异常原因分析。

    Args:
        anomaly_id: 待归因异常编号。
        session: 数据库异步会话。
        current_user: 当前登录用户。

    Returns:
        多个带置信度和证据的原因假设。

    Raises:
        HTTPException: 异常不可访问或归因输入无效。
    """
    anomaly = await session.get(
        AnomalyRecord,
        anomaly_id,
    )
    if anomaly is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="异常记录不存在",
        )

    campaign = await get_campaign(
        session,
        anomaly.campaign_id,
        current_user,
    )

    if campaign is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="异常记录不存在",
        )

    try:
        result = await analyze_anomaly_cause(
            session,
            anomaly.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_CONTENT
            ),
            detail=str(exc),
        ) from exc

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="异常记录不存在",
        )

    return result


@router.get(
    "/{anomaly_id}/cause",
    response_model=None,
)
async def anomaly_cause_detail(
    anomaly_id: AnomalyId,
    session: SessionDep,
    current_user: CurrentUser,
) -> CauseAnalysisResult:
    """查询异常已有的原因假设。

    Args:
        anomaly_id: 异常编号。
        session: 数据库异步会话。
        current_user: 当前登录用户。

    Returns:
        已保存的原因假设和数据充分性信息。

    Raises:
        HTTPException: 异常不可访问或尚未完成归因。
    """
    anomaly = await session.get(
        AnomalyRecord,
        anomaly_id,
    )

    if anomaly is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="异常记录不存在",
        )

    campaign = await get_campaign(
        session,
        anomaly.campaign_id,
        current_user,
    )

    if campaign is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="异常记录不存在",
        )

    result = await get_anomaly_cause_result(
        session,
        anomaly.id,
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="异常原因不存在",
        )

    return result


@router.post(
    "/{anomaly_id}/suggestions/generate",
    response_model=None,
)
async def intervention_suggestions_generate(
    anomaly_id: AnomalyId,
    session: SessionDep,
    current_user: CurrentUser,
) -> SuggestionGenerationResult:
    """为指定异常生成投放干预建议。

    Args:
        anomaly_id: 需要生成建议的异常编号。
        session: 数据库异步会话。
        current_user: 当前登录用户。

    Returns:
        主建议、备选建议、数据充分性及案例召回状态。

    Raises:
        HTTPException: 异常不存在、用户无权访问，
            或建议生成条件不满足。
    """
    anomaly = await session.get(
        AnomalyRecord,
        anomaly_id,
    )

    if anomaly is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="异常记录不存在",
        )

    campaign = await get_campaign(
        session,
        anomaly.campaign_id,
        current_user,
    )

    if campaign is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="异常记录不存在",
        )

    try:
        result = (
            await generate_intervention_suggestions(
                session,
                anomaly.id,
            )
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_CONTENT
            ),
            detail=str(exc),
        ) from exc

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="异常记录不存在",
        )

    return result


@router.get(
    "/{anomaly_id}/suggestions",
    response_model=None,
)
async def intervention_suggestions_detail(
    anomaly_id: AnomalyId,
    session: SessionDep,
    current_user: CurrentUser,
) -> SuggestionGenerationResult:
    """查询指定异常已经生成的干预建议。

    Args:
        anomaly_id: 需要查询建议的异常编号。
        session: 数据库异步会话。
        current_user: 当前登录用户。

    Returns:
        主建议、备选建议、数据充分性及案例召回状态。

    Raises:
        HTTPException: 异常不可访问或尚未生成建议。
    """
    anomaly = await session.get(
        AnomalyRecord,
        anomaly_id,
    )

    if anomaly is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="异常记录不存在",
        )

    campaign = await get_campaign(
        session,
        anomaly.campaign_id,
        current_user,
    )

    if campaign is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="异常记录不存在",
        )

    result = await get_intervention_suggestion_result(
        session,
        anomaly.id,
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="干预建议不存在",
        )

    return result
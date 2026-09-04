from fastapi import APIRouter
from app.api.routing import UnifiedResponseRoute
from app.api.dependencies.auth import CurrentUser, SessionDep
from app.schemas import AudienceRead, ChannelRead, CreativeRead, ProductRead
from app.services.catalog import (
    list_audiences,
    list_channels,
    list_creatives,
    list_products,
)


router = APIRouter(
    tags=["catalog"],
    route_class=UnifiedResponseRoute
)

@router.get("/products",response_model=None)
async def product_list(
    session: SessionDep,
    _:CurrentUser,
) -> list[ProductRead]:
    """查询可用产品。

    Args:
        session: 数据库异步会话。
        _: 未使用的框架注入参数。

    Returns:
        返回类型为 list[ProductRead] 的执行结果。
    """
    products = await list_products(session)

    return [
        ProductRead.model_validate(product)
        for product in products
    ]

@router.get("/channels",response_model=None)
async def channel_list(
    session:SessionDep,
    _:CurrentUser,
) -> list[ChannelRead]:
    """查询可用渠道。

    Args:
        session: 数据库异步会话。
        _: 未使用的框架注入参数。

    Returns:
        返回类型为 list[ChannelRead] 的执行结果。
    """
    channels = await list_channels(session)

    return [
        ChannelRead.model_validate(channel)
        for channel in channels
    ]

@router.get("/audiences", response_model=None)
async def audience_list(
    session: SessionDep,
    _: CurrentUser,
) -> list[AudienceRead]:
    """查询可用人群。

    Args:
        session: 数据库异步会话。
        _: 未使用的框架注入参数。

    Returns:
        返回类型为 list[AudienceRead] 的执行结果。
    """
    audiences = await list_audiences(session)

    return [
        AudienceRead.model_validate(audience)
        for audience in audiences
    ]

@router.get("/creatives", response_model=None)
async def creative_list(
    session: SessionDep,
    _: CurrentUser,
) -> list[CreativeRead]:
    """查询已审核素材。

    Args:
        session: 数据库异步会话。
        _: 未使用的框架注入参数。

    Returns:
        返回类型为 list[CreativeRead] 的执行结果。
    """
    creatives = await list_creatives(session)

    return [
        CreativeRead.model_validate(creative)
        for creative in creatives
    ]

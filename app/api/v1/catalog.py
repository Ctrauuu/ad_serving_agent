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
    creatives = await list_creatives(session)

    return [
        CreativeRead.model_validate(creative)
        for creative in creatives
    ]
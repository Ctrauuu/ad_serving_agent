from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Audience, Channel, Creative, Product

async def list_products(session:AsyncSession) -> list[Product]:
    result = await session.scalars(
        select(Product)
        .where(Product.status == "启用")
        .order_by(Product.id)
    )

    return list(result.all())

async def list_channels(session:AsyncSession) -> list[Channel]:
    result = await session.scalars(
        select(Channel)
        .where(Channel.status == "启用")
        .order_by(Channel.id)
    )

    return list(result.all())

async def list_audiences(session: AsyncSession) -> list[Audience]:
    result = await session.scalars(
        select(Audience)
        .where(Audience.status == "启用")
        .order_by(Audience.id)
    )
    return list(result.all())

async def list_creatives(session: AsyncSession) -> list[Creative]:
    result = await session.scalars(
        select(Creative)
        .where(Creative.status == "已审核")
        .order_by(Creative.id)
    )
    return list(result.all())
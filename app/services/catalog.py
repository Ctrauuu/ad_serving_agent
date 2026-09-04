from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Audience, Channel, Creative, Product

async def list_products(session:AsyncSession) -> list[Product]:
    """查询启用产品。

    Args:
        session: 数据库异步会话。

    Returns:
        返回类型为 list[Product] 的执行结果。
    """
    result = await session.scalars(
        select(Product)
        .where(Product.status == "启用")
        .order_by(Product.id)
    )

    return list(result.all())

async def list_channels(session:AsyncSession) -> list[Channel]:
    """查询启用渠道。

    Args:
        session: 数据库异步会话。

    Returns:
        返回类型为 list[Channel] 的执行结果。
    """
    result = await session.scalars(
        select(Channel)
        .where(Channel.status == "启用")
        .order_by(Channel.id)
    )

    return list(result.all())

async def list_audiences(session: AsyncSession) -> list[Audience]:
    """查询启用人群。

    Args:
        session: 数据库异步会话。

    Returns:
        返回类型为 list[Audience] 的执行结果。
    """
    result = await session.scalars(
        select(Audience)
        .where(Audience.status == "启用")
        .order_by(Audience.id)
    )
    return list(result.all())

async def list_creatives(session: AsyncSession) -> list[Creative]:
    """查询已审核素材。

    Args:
        session: 数据库异步会话。

    Returns:
        返回类型为 list[Creative] 的执行结果。
    """
    result = await session.scalars(
        select(Creative)
        .where(Creative.status == "已审核")
        .order_by(Creative.id)
    )
    return list(result.all())

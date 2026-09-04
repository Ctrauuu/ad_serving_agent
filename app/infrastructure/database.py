from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """提供数据库异步会话。

    Returns:
        返回类型为 AsyncGenerator[AsyncSession, None] 的执行结果。
    """
    async with async_session() as session:
        yield session


async def check_database() -> None:
    """检查数据库连接。

    Returns:
        无返回值。
    """
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))

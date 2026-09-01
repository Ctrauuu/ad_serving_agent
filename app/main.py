from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool

from app.api.v1.router import router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.infrastructure.database import check_database, engine
from app.infrastructure.milvus import milvus_client
from app.infrastructure.redis import redis_client


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        await check_database()
        await redis_client.ping() # type: ignore
        await run_in_threadpool(milvus_client.initialize)
    except Exception as exc:
        await redis_client.aclose()
        await engine.dispose()
        raise RuntimeError(f"Dependency startup check failed: {exc}") from exc
    try:
        yield
    finally:
        await redis_client.aclose()
        await run_in_threadpool(milvus_client.close)
        await engine.dispose()


app = FastAPI(title=get_settings().app_name, lifespan=lifespan)
app.include_router(router)
register_exception_handlers(app)

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from app.api.routing import UnifiedResponseRoute
from app.infrastructure.database import check_database
from app.infrastructure.milvus import milvus_client
from app.infrastructure.redis import redis_client

router = APIRouter(route_class=UnifiedResponseRoute)


@router.get("/health")
async def health() -> dict[str, object]:
    """检查应用依赖健康状态。

    Returns:
        返回类型为 dict[str, object] 的执行结果。
    """
    try:
        await check_database()
        await redis_client.ping() # type: ignore
        await run_in_threadpool(milvus_client.check)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"dependency unavailable: {exc}") from exc
    return {"status": "up", "dependencies": {"mysql": "up", "redis": "up", "milvus": "up"}}

import json
from collections.abc import Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute

from app.core.responses import ok


class UnifiedResponseRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Any]:
        """获取并包装路由处理器。

        Returns:
            返回类型为 Callable[[Request], Any] 的执行结果。
        """
        handler = super().get_route_handler()

        async def wrapped(request: Request) -> Response:
            """包装统一 API 响应。

            Args:
                request: 当前 HTTP 请求。

            Returns:
                返回类型为 Response 的执行结果。
            """
            response = await handler(request)
            if response.status_code >= 400 or not response.headers.get("content-type", "").startswith("application/json"):
                return response
            payload = json.loads(response.body)
            if isinstance(payload, dict) and {"code", "message", "data"} <= payload.keys():
                return response
            return JSONResponse(status_code=response.status_code, content=ok(payload))

        return wrapped

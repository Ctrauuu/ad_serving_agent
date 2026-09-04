import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.responses import error

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    """注册统一异常处理器。

    Args:
        app: FastAPI 应用实例。

    Returns:
        无返回值。
    """
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        """处理请求校验异常。

        Args:
            _: 未使用的框架注入参数。
            exc: 捕获到的异常。

        Returns:
            返回类型为 JSONResponse 的执行结果。
        """
        return JSONResponse(status_code=422, content=error(422, "validation error", exc.errors()))

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
        """处理 HTTP 异常。

        Args:
            _: 未使用的框架注入参数。
            exc: 捕获到的异常。

        Returns:
            返回类型为 JSONResponse 的执行结果。
        """
        return JSONResponse(
            status_code=exc.status_code, content=error(exc.status_code, str(exc.detail)),
            headers=exc.headers if exc.headers else None
            )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
        """处理未捕获异常。

        Args:
            _: 未使用的框架注入参数。
            exc: 捕获到的异常。

        Returns:
            返回类型为 JSONResponse 的执行结果。
        """
        logger.exception("Unhandled request error", exc_info=exc)
        return JSONResponse(status_code=500, content=error(500, "internal server error"))

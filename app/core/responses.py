from typing import Any

from pydantic import BaseModel


class ApiResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: Any = None


def ok(data: Any = None, message: str = "ok") -> dict[str, Any]:
    """构造统一成功响应。

    Args:
        data: 响应业务数据。
        message: 响应提示。

    Returns:
        返回类型为 dict[str, Any] 的执行结果。
    """
    return ApiResponse(message=message, data=data).model_dump()


def error(code: int, message: str, data: Any = None) -> dict[str, Any]:
    """构造统一错误响应。

    Args:
        code: 业务错误码。
        message: 响应提示。
        data: 响应业务数据。

    Returns:
        返回类型为 dict[str, Any] 的执行结果。
    """
    return ApiResponse(code=code, message=message, data=data).model_dump()

from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import (
    streamable_http_client,
)
from mcp.types import TextContent

from app.core.config import get_settings


async def call_ad_platform_tool(
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """调用模拟广告平台 MCP 工具。

    Args:
        tool_name: MCP 工具名称。
        arguments: MCP 工具参数。

    Returns:
        返回类型为 dict[str, Any] 的执行结果。
    """
    settings = get_settings()

    try:
        async with streamable_http_client(
            settings.ad_platform_mcp_url
        ) as (read, write, _):
            async with ClientSession(
                read,
                write,
            ) as session:
                await session.initialize()

                result = await session.call_tool(
                    tool_name,
                    arguments,
                )
    except Exception as exc:
        raise RuntimeError(
            "无法连接模拟广告平台"
        ) from exc

    if result.isError:
        message = next(
            (
                block.text
                for block in result.content
                if isinstance(block, TextContent)
            ),
            "未知平台错误",
        )

        raise ValueError(
            f"模拟广告平台调用失败：{message}"
        )

    data = result.structuredContent

    if not isinstance(data, dict):
        raise RuntimeError(
            "模拟广告平台未返回结构化结果"
        )

    return data

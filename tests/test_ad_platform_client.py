from types import SimpleNamespace

import pytest
from mcp.types import TextContent

from app.infrastructure.ad_platform import (
    call_ad_platform_tool,
)


class AsyncContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *_):
        return None


@pytest.mark.asyncio
async def test_call_ad_platform_tool_handles_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = iter(
        [
            SimpleNamespace(
                isError=False,
                structuredContent={"status": "已上线"},
                content=[],
            ),
            SimpleNamespace(
                isError=True,
                structuredContent=None,
                content=[
                    TextContent(
                        type="text",
                        text="平台任务不存在",
                    )
                ],
            ),
        ]
    )

    class FakeSession:
        def __init__(self, *_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def initialize(self):
            return None

        async def call_tool(self, *_):
            return next(results)

    monkeypatch.setattr(
        "app.infrastructure.ad_platform.streamable_http_client",
        lambda _: AsyncContext((object(), object(), None)),
    )
    monkeypatch.setattr(
        "app.infrastructure.ad_platform.ClientSession",
        FakeSession,
    )

    assert await call_ad_platform_tool("status", {}) == {
        "status": "已上线"
    }

    with pytest.raises(ValueError, match="平台任务不存在"):
        await call_ad_platform_tool("status", {})

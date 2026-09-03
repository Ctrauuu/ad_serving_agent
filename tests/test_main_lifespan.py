from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_lifespan_starts_and_stops_scheduler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = import_module("app.main")
    start = MagicMock()
    stop = MagicMock()

    monkeypatch.setattr(
        main,
        "check_database",
        AsyncMock(),
    )
    monkeypatch.setattr(
        main.redis_client,
        "ping",
        AsyncMock(),
    )
    monkeypatch.setattr(
        main.redis_client,
        "aclose",
        AsyncMock(),
    )
    monkeypatch.setattr(
        main,
        "engine",
        SimpleNamespace(dispose=AsyncMock()),
    )
    monkeypatch.setattr(
        main,
        "run_in_threadpool",
        AsyncMock(),
    )
    monkeypatch.setattr(
        main,
        "start_metric_scheduler",
        start,
    )
    monkeypatch.setattr(
        main,
        "stop_metric_scheduler",
        stop,
    )

    async with main.lifespan(main.app):
        start.assert_called_once_with()
        stop.assert_not_called()

    stop.assert_called_once_with()

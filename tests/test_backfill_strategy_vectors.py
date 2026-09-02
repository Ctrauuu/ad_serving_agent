from unittest.mock import AsyncMock, MagicMock

import pytest

from app.scripts.backfill_strategy_vectors import (
    backfill_strategy_vectors,
)


@pytest.mark.asyncio
async def test_backfill_indexes_valid_confirmed_strategy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    result = MagicMock()
    result.all.return_value = [
        (
            21,
            8,
            {
                "product": "企业HR系统",
                "audience": "企业HR负责人",
                "budget": 80000,
                "cycle": "2026年9月",
                "conversion_goal": "线索",
                "channels": ["信息流"],
                "risk": "单条线索成本不超过300元",
            },
        ),
        (22, 9, None),
    ]
    session.execute.return_value = result

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(
        return_value=session
    )
    session_context.__aexit__ = AsyncMock(
        return_value=None
    )
    monkeypatch.setattr(
        "app.scripts.backfill_strategy_vectors.async_session",
        lambda: session_context,
    )

    captured: dict[str, object] = {}

    async def fake_embed_goal(goal, text_type):
        captured["text_type"] = text_type
        return [0.1] * 1024

    async def fake_upsert_strategy_vector(
        strategy_id,
        campaign_id,
        goal_vector,
    ):
        captured.update(
            strategy_id=strategy_id,
            campaign_id=campaign_id,
            vector_length=len(goal_vector),
        )

    monkeypatch.setattr(
        "app.scripts.backfill_strategy_vectors.embed_goal",
        fake_embed_goal,
    )
    monkeypatch.setattr(
        (
            "app.scripts.backfill_strategy_vectors."
            "milvus_client.upsert_strategy_vector"
        ),
        fake_upsert_strategy_vector,
    )

    assert await backfill_strategy_vectors() == (1, 1)
    assert captured == {
        "text_type": "document",
        "strategy_id": 21,
        "campaign_id": 8,
        "vector_length": 1024,
    }

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models import CaseLibrary
from app.scripts.backfill_intervention_case_vectors import (
    backfill_intervention_case_vectors,
)


@pytest.mark.asyncio
async def test_backfill_indexes_intervention_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证回填脚本使用 document 向量并写入案例主键。"""
    case = CaseLibrary(
        id=1,
        case_type="intervention",
        scene_desc="CPA 持续上升",
        cause="素材疲劳",
        action="replace_creative",
        effectiveness="有效",
    )
    session = AsyncMock()
    result = MagicMock()
    result.all.return_value = [case]
    session.scalars.return_value = result
    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(
        return_value=session
    )
    session_context.__aexit__ = AsyncMock(return_value=None)
    embed = AsyncMock(return_value=[0.2] * 1024)
    upsert = AsyncMock()
    monkeypatch.setattr(
        "app.scripts.backfill_intervention_case_vectors.async_session",
        lambda: session_context,
    )
    monkeypatch.setattr(
        "app.scripts.backfill_intervention_case_vectors.embed_text",
        embed,
    )
    monkeypatch.setattr(
        (
            "app.scripts.backfill_intervention_case_vectors."
            "milvus_client.upsert_intervention_case_vector"
        ),
        upsert,
    )

    count = await backfill_intervention_case_vectors()

    assert count == 1
    embed.assert_awaited_once()
    assert embed.await_args.kwargs["text_type"] == "document"
    upsert.assert_awaited_once_with(
        case_id=1,
        intervention_vector=[0.2] * 1024,
    )

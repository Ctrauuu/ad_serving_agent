from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models import CaseLibrary
from app.scripts.backfill_anomaly_case_vectors import (
    format_case_scene,
    main,
)


def test_format_case_scene_uses_searchable_fields() -> None:
    """验证向量文本只包含异常类型和场景。"""
    case = CaseLibrary(
        id=3,
        case_type="anomaly",
        anomaly_type="valid_lead_drop",
        scene_desc="CTR 上升但有效线索率下降",
        cause="素材疲劳",
        effectiveness="有效",
    )

    text = format_case_scene(case)

    assert "valid_lead_drop" in text
    assert "CTR 上升但有效线索率下降" in text
    assert "素材疲劳" not in text


@pytest.mark.asyncio
async def test_backfill_indexes_anomaly_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证回填脚本以 document 类型写入案例向量。"""
    case = CaseLibrary(
        id=3,
        case_type="anomaly",
        anomaly_type="valid_lead_drop",
        scene_desc="有效线索率下降",
        cause="素材疲劳",
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
    session_context.__aexit__ = AsyncMock(
        return_value=None
    )
    captured: dict[str, object] = {}

    async def fake_embed_text(
        text: str,
        text_type: str,
    ) -> list[float]:
        """记录向量化参数并返回固定向量。"""
        captured.update(text=text, text_type=text_type)
        return [0.1] * 1024

    async def fake_upsert(
        case_id: int,
        scene_vector: list[float],
    ) -> None:
        """记录 Milvus 写入参数。"""
        captured.update(
            case_id=case_id,
            vector_length=len(scene_vector),
        )

    monkeypatch.setattr(
        "app.scripts.backfill_anomaly_case_vectors.async_session",
        lambda: session_context,
    )
    monkeypatch.setattr(
        "app.scripts.backfill_anomaly_case_vectors.embed_text",
        fake_embed_text,
    )
    monkeypatch.setattr(
        (
            "app.scripts.backfill_anomaly_case_vectors."
            "milvus_client.upsert_anomaly_case_vector"
        ),
        fake_upsert,
    )
    monkeypatch.setattr(
        "app.scripts.backfill_anomaly_case_vectors.milvus_client.initialize",
        MagicMock(),
    )
    monkeypatch.setattr(
        "app.scripts.backfill_anomaly_case_vectors.milvus_client.close",
        MagicMock(),
    )
    monkeypatch.setattr(
        "app.scripts.backfill_anomaly_case_vectors.engine",
        SimpleNamespace(dispose=AsyncMock()),
    )

    await main()

    assert captured["text_type"] == "document"
    assert captured["case_id"] == 3
    assert captured["vector_length"] == 1024

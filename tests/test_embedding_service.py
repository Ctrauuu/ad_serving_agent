from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.schemas import StructuredGoal
from app.services.embedding import embed_goal, embed_text


@pytest.mark.asyncio
async def test_embed_goal_returns_configured_vector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证目标格式化后使用统一向量服务。"""
    captured: dict[str, object] = {}

    def fake_embedding_call(**kwargs: object) -> SimpleNamespace:
        """返回固定长度的模拟向量。"""
        captured.update(kwargs)
        return SimpleNamespace(
            status_code=200,
            output={
                "embeddings": [
                    {"embedding": [0.1] * 1024}
                ]
            },
        )

    monkeypatch.setattr(
        "app.services.embedding.TextEmbedding.call",
        fake_embedding_call,
    )

    goal = StructuredGoal(
        product="企业HR系统",
        audience="中小企业HR负责人",
        budget=Decimal("80000"),
        cycle="2026年9月1日至9月30日",
        conversion_goal="线索",
        channels=["信息流", "搜索广告"],
        risk="单条线索成本不超过300元",
    )

    vector = await embed_goal(goal, text_type="document")

    assert len(vector) == 1024
    assert captured["model"] == "text-embedding-v3"
    assert captured["dimension"] == 1024
    assert captured["text_type"] == "document"
    assert "企业HR系统" in str(captured["input"])


@pytest.mark.asyncio
async def test_embed_text_rejects_blank_text() -> None:
    """验证空白文本不会请求百炼接口。"""
    with pytest.raises(ValueError, match="不能为空"):
        await embed_text("   ", text_type="query")

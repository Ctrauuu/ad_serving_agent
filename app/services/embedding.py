from typing import Literal
from app.schemas import StructuredGoal
from app.core.config import get_settings
from dashscope import TextEmbedding
from asyncio import to_thread
from http import HTTPStatus


EmbeddingTextType = Literal["document","query"]

def _format_goal(goal:StructuredGoal) -> str:
    return "\n".join(
        [
            f"产品：{goal.product}",
            f"目标人群：{goal.audience}",
            f"预算：{goal.budget}",
            f"投放周期：{goal.cycle}",
            f"转化目标：{goal.conversion_goal}",
            f"投放渠道：{'、'.join(goal.channels)}",
            f"风险限制：{goal.risk}",
        ]
    )

async def embed_goal(
    goal:StructuredGoal,
    text_type:EmbeddingTextType,
) -> list[float]:
    settings = get_settings()

    response = await to_thread(
        TextEmbedding.call,
        model = settings.dashscope_embedding_model,
        input = _format_goal(goal),
        api_key = settings.dashscope_api_key.get_secret_value(),
        text_type=text_type,
        dimension = settings.milvus_vector_dim,
    )

    if response.status_code != HTTPStatus.OK:
        raise RuntimeError(
            f"百炼 Embedding 调用失败："
            f"{response.code} {response.message}"
        )

    vector = response.output["embeddings"][0]["embedding"]

    if len(vector) != settings.milvus_vector_dim:
        raise ValueError(
            f"Embedding 维度错误：期望 "
            f"{settings.milvus_vector_dim}，实际 {len(vector)}"
        )

    return list(vector)
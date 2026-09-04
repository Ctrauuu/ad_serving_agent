from asyncio import to_thread
from http import HTTPStatus
from typing import Literal

from dashscope import TextEmbedding

from app.core.config import get_settings
from app.schemas import StructuredGoal


EmbeddingTextType = Literal["document", "query"]


def _format_goal(goal: StructuredGoal) -> str:
    """格式化结构化目标文本。

    Args:
        goal: 结构化投放目标。

    Returns:
        返回类型为 str 的执行结果。
    """
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

async def embed_text(
    text: str,
    text_type: EmbeddingTextType,
) -> list[float]:
    """把文本转换为百炼语义向量。

    Args:
        text: 需要向量化的文本。
        text_type: 文本用途，document 表示入库文档，
            query 表示检索条件。

    Returns:
        长度等于 Milvus 向量维度的浮点数列表。

    Raises:
        ValueError: 文本为空或向量维度不正确。
        RuntimeError: 百炼 Embedding 调用失败。
    """
    if not text.strip():
        raise ValueError("向量化文本不能为空")

    settings = get_settings()

    response = await to_thread(
        TextEmbedding.call,
        model=settings.dashscope_embedding_model,
        input=text,
        api_key=(
            settings.dashscope_api_key.get_secret_value()
        ),
        text_type=text_type,
        dimension=settings.milvus_vector_dim,
    )

    if response.status_code != HTTPStatus.OK:
        raise RuntimeError(
            "百炼 Embedding 调用失败："
            f"{response.code} {response.message}"
        )

    vector = response.output[
        "embeddings"
    ][0]["embedding"]

    if len(vector) != settings.milvus_vector_dim:
        raise ValueError(
            "Embedding 维度错误：期望 "
            f"{settings.milvus_vector_dim}，"
            f"实际 {len(vector)}"
        )

    return list(vector)


async def embed_goal(
    goal: StructuredGoal,
    text_type: EmbeddingTextType,
) -> list[float]:
    """生成投放目标向量。

    Args:
        goal: 结构化投放目标。
        text_type: Embedding 文本用途。

    Returns:
        结构化目标对应的语义向量。
    """
    return await embed_text(
        _format_goal(goal),
        text_type,
    )

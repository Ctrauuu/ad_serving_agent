import asyncio

from sqlalchemy import select

from app.infrastructure.database import async_session, engine
from app.infrastructure.milvus import milvus_client
from app.models import CaseLibrary
from app.services.embedding import embed_text
from app.services.suggestion import format_intervention_case


async def backfill_intervention_case_vectors() -> int:
    """回填历史干预案例的 Milvus 向量。

    Returns:
        成功写入 Milvus 的历史干预案例数量。

    Raises:
        RuntimeError: Embedding 或 Milvus 调用失败。
    """
    indexed_count = 0

    async with async_session() as session:
        cases = list(
            (
                await session.scalars(
                    select(CaseLibrary)
                    .where(
                        CaseLibrary.case_type
                        == "intervention",
                        CaseLibrary.action.is_not(None),
                    )
                    .order_by(CaseLibrary.id)
                )
            ).all()
        )

        for case in cases:
            case_text = format_intervention_case(
                case
            )
            case_vector = await embed_text(
                case_text,
                text_type="document",
            )

            await (
                milvus_client
                .upsert_intervention_case_vector(
                    case_id=case.id,
                    intervention_vector=case_vector,
                )
            )

            indexed_count += 1
            print(
                f"已索引干预案例 {case.id}："
                f"{case.action}"
            )

    return indexed_count


async def main() -> None:
    """执行历史干预案例向量回填。

    Returns:
        无返回值。
    """
    milvus_client.initialize()

    try:
        indexed_count = (
            await backfill_intervention_case_vectors()
        )
        print(
            f"回填完成：成功 {indexed_count} 条"
        )
    finally:
        milvus_client.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

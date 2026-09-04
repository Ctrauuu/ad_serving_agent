import asyncio

from pydantic import ValidationError
from sqlalchemy import select

from app.infrastructure.database import async_session, engine
from app.infrastructure.milvus import milvus_client
from app.models import Campaign, Strategy
from app.schemas.campaign import StructuredGoal
from app.services.embedding import embed_goal


async def backfill_strategy_vectors() -> tuple[int, int]:
    """回填历史策略向量。

    Returns:
        返回类型为 tuple[int, int] 的执行结果。
    """
    indexed_count = 0
    skipped_count = 0

    async with async_session() as session:
        result = await session.execute(
            select(
                Strategy.id,
                Strategy.campaign_id,
                Campaign.structured_goal,
            )
            .join(
                Campaign,
                Campaign.id == Strategy.campaign_id,
            )
            .where(Strategy.status == "已确认")
            .order_by(Strategy.id)
        )

        rows = result.all()

        for strategy_id, campaign_id, goal_data in rows:
            try:
                structured_goal = StructuredGoal.model_validate(
                    goal_data
                )
            except ValidationError:
                skipped_count += 1
                print(
                    f"跳过策略 {strategy_id}："
                    "structured_goal 缺失或格式不完整"
                )
                continue

            goal_vector = await embed_goal(
                structured_goal,
                text_type="document",
            )

            await milvus_client.upsert_strategy_vector(
                strategy_id=strategy_id,
                campaign_id=campaign_id,
                goal_vector=goal_vector,
            )

            indexed_count += 1
            print(
                f"已索引策略 {strategy_id}，"
                f"活动 {campaign_id}"
            )

    return indexed_count, skipped_count


async def main() -> None:
    """执行命令行脚本入口。

    Returns:
        无返回值。
    """
    milvus_client.initialize()

    try:
        indexed_count, skipped_count = (
            await backfill_strategy_vectors()
        )

        print(
            "回填完成："
            f"成功 {indexed_count} 条，"
            f"跳过 {skipped_count} 条"
        )
    finally:
        milvus_client.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

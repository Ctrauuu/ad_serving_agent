import asyncio

from sqlalchemy import select

from app.infrastructure.database import (
    async_session,
    engine,
)
from app.infrastructure.milvus import milvus_client
from app.models import CaseLibrary
from app.services.embedding import embed_text


def format_case_scene(case: CaseLibrary) -> str:
    """把历史案例整理成用于检索的异常场景文本。

    Args:
        case: MySQL 中的历史案例。

    Returns:
        包含异常类型和场景描述的稳定文本。
    """
    return "\n".join(
        [
            f"异常类型：{case.anomaly_type or '未分类'}",
            f"异常场景：{case.scene_desc}",
        ]
    )


async def main() -> None:
    """向量化有效的异常案例并写入 Milvus。

    Returns:
        无返回值。
    """
    milvus_client.initialize()

    try:
        async with async_session() as session:
            cases = list(
                (
                    await session.scalars(
                        select(CaseLibrary).where(
                            CaseLibrary.case_type.in_(
                                ["anomaly", "intervention"]
                            ),
                            CaseLibrary.cause.is_not(None),
                        )
                    )
                ).all()
            )

            for case in cases:
                scene_vector = await embed_text(
                    format_case_scene(case),
                    text_type="document",
                )
                await (
                    milvus_client
                    .upsert_anomaly_case_vector(
                        case_id=case.id,
                        scene_vector=scene_vector,
                    )
                )
                print(
                    f"已索引异常案例 {case.id}："
                    f"{case.cause}"
                )

            print(f"共索引 {len(cases)} 条异常案例")
    finally:
        milvus_client.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
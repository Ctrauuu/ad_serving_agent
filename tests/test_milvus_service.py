from unittest.mock import MagicMock

import pytest

from app.infrastructure.milvus import MilvusService


@pytest.mark.asyncio
async def test_upsert_and_search_strategy_vectors() -> None:
    """验证策略向量写入参数与召回结果转换。"""
    service = MilvusService()
    client = MagicMock()
    service._client = client

    vector = [0.1] * 1024

    await service.upsert_strategy_vector(
        strategy_id=11,
        campaign_id=3,
        goal_vector=vector,
    )

    client.search.return_value = [
        [
            {
                "strategy_id": 11,
                "distance": 0.91,
                "entity": {
                    "campaign_id": 3,
                },
            }
        ]
    ]

    matches = await service.search_similar_strategies(  # type: ignore
        goal_vector=vector,
        current_campaign_id=9,
        limit=5,
    )

    upsert_data = client.upsert.call_args.kwargs["data"]
    assert upsert_data == [
        {
            "strategy_id": 11,
            "campaign_id": 3,
            "goal_vector": vector,
        }
    ]

    search_args = client.search.call_args.kwargs
    assert search_args["filter"] == "campaign_id != 9"
    assert search_args["limit"] == 5
    assert search_args["search_params"]["metric_type"] == "COSINE"

    assert matches == [
        {
            "strategy_id": 11,
            "campaign_id": 3,
            "score": 0.91,
        }
    ]


@pytest.mark.asyncio
async def test_upsert_and_search_anomaly_case_vectors() -> None:
    """验证异常案例向量写入参数与召回结果转换。"""
    service = MilvusService()
    client = MagicMock()
    service._client = client
    vector = [0.2] * 1024

    await service.upsert_anomaly_case_vector(
        case_id=21,
        scene_vector=vector,
    )

    client.search.return_value = [
        [
            {
                "case_id": 21,
                "distance": 0.88,
            }
        ]
    ]
    matches = await service.search_similar_anomaly_cases(
        scene_vector=vector,
        limit=3,
    )

    assert client.upsert.call_args.kwargs["data"] == [
        {
            "case_id": 21,
            "scene_vector": vector,
        }
    ]
    search_args = client.search.call_args.kwargs
    assert search_args["limit"] == 3
    assert search_args["search_params"]["metric_type"] == "COSINE"
    assert matches == [{"case_id": 21, "score": 0.88}]

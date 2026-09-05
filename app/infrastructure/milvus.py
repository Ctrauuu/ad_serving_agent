from asyncio import to_thread

from pymilvus import DataType, MilvusClient

from app.core.config import get_settings


class MilvusService:
    def __init__(self) -> None:
        """初始化客户端状态。

        Returns:
            无返回值。
        """
        self._client: MilvusClient | None = None

    def _require_client(self) -> MilvusClient:
        """获取已初始化的客户端。

        Returns:
            返回类型为 MilvusClient 的执行结果。
        """
        if self._client is None:
            raise RuntimeError("Milvus client is not initialized")
        return self._client

    def initialize(self) -> None:
        """初始化连接及依赖资源。

        Returns:
            无返回值。
        """
        settings = get_settings()
        self._client = MilvusClient(
            uri=settings.milvus_uri,
            token=settings.milvus_token,  # type: ignore
        )

        if not self._client.has_collection(settings.milvus_collection):
            self._client.create_collection(
                collection_name=settings.milvus_collection,
                dimension=settings.milvus_vector_dim,
            )
        if not self._client.has_collection(
            settings.milvus_campaign_strategy_collection
        ):
            schema = MilvusClient.create_schema(
                auto_id=False,
                enable_dynamic_field=False,
            )
            schema.add_field(
                field_name="strategy_id",
                datatype=DataType.INT64,
                is_primary=True,
            )
            schema.add_field(
                field_name="campaign_id",
                datatype=DataType.INT64,
            )
            schema.add_field(
                field_name="goal_vector",
                datatype=DataType.FLOAT_VECTOR,
                dim=settings.milvus_vector_dim,
            )

            index_params = self._client.prepare_index_params()
            index_params.add_index(
                field_name="goal_vector",
                index_type="AUTOINDEX",
                metric_type="COSINE",
            )
            self._client.create_collection(
                collection_name=settings.milvus_campaign_strategy_collection,
                schema=schema,
                index_params=index_params,
            )

        if not self._client.has_collection(
            settings.milvus_anomaly_case_collection
        ):
            anomaly_schema = MilvusClient.create_schema(
                auto_id=False,
                enable_dynamic_field=False,
            )
            anomaly_schema.add_field(
                field_name="case_id",
                datatype=DataType.INT64,
                is_primary=True,
            )
            anomaly_schema.add_field(
                field_name="scene_vector",
                datatype=DataType.FLOAT_VECTOR,
                dim=settings.milvus_vector_dim,
            )

            anomaly_index = (
                self._client.prepare_index_params()
            )
            anomaly_index.add_index(
                field_name="scene_vector",
                index_type="AUTOINDEX",
                metric_type="COSINE",
            )

            self._client.create_collection(
                collection_name=(
                    settings.milvus_anomaly_case_collection
                ),
                schema=anomaly_schema,
                index_params=anomaly_index,
            )

        if not self._client.has_collection(
            settings.milvus_intervention_case_collection
        ):
            intervention_schema = (
                MilvusClient.create_schema(
                    auto_id=False,
                    enable_dynamic_field=False,
                )
            )
            intervention_schema.add_field(
                field_name="case_id",
                datatype=DataType.INT64,
                is_primary=True,
            )
            intervention_schema.add_field(
                field_name="intervention_vector",
                datatype=DataType.FLOAT_VECTOR,
                dim=settings.milvus_vector_dim,
            )

            intervention_index = (
                self._client.prepare_index_params()
            )
            intervention_index.add_index(
                field_name="intervention_vector",
                index_type="AUTOINDEX",
                metric_type="COSINE",
            )

            self._client.create_collection(
                collection_name=(
                    settings
                    .milvus_intervention_case_collection
                ),
                schema=intervention_schema,
                index_params=intervention_index,
            )


    def check(self) -> None:
        """检查依赖服务是否可用。

        Returns:
            无返回值。
        """
        client = self._require_client()
        client.has_collection(
            get_settings().milvus_collection
        )  # type: ignore

    async def upsert_strategy_vector(
        self,
        strategy_id: int,
        campaign_id: int,
        goal_vector: list[float],
    ) -> None:
        """写入或更新策略向量。

        Args:
            strategy_id: 策略编号。
            campaign_id: 活动编号。
            goal_vector: 目标向量。

        Returns:
            无返回值。
        """
        client = self._require_client()
        settings = get_settings()

        await to_thread(
            client.upsert,
            collection_name=settings.milvus_campaign_strategy_collection,
            data=[
                {
                    "strategy_id": strategy_id,
                    "campaign_id": campaign_id,
                    "goal_vector": goal_vector,
                }
            ],
        )

    async def search_similar_strategies(
        self,
        goal_vector: list[float],
        current_campaign_id: int,
        limit: int = 5,
    ) -> list[dict[str, int | float]]:
        """召回相似历史策略。

        Args:
            goal_vector: 目标向量。
            current_campaign_id: 当前活动编号。
            limit: 最大返回数量。

        Returns:
            返回类型为 list[dict[str, int | float]] 的执行结果。
        """
        client = self._require_client()
        settings = get_settings()

        results = await to_thread(
            client.search,
            collection_name=settings.milvus_campaign_strategy_collection,
            data=[goal_vector],
            anns_field="goal_vector",
            filter=f"campaign_id != {int(current_campaign_id)}",
            limit=limit,
            output_fields=["campaign_id"],
            search_params={
                "metric_type": "COSINE",
                "params": {},
            },
            consistency_level="Strong",
        )

        hits = results[0] if results else []

        return [
            {
                "strategy_id": int(hit["strategy_id"]),
                "campaign_id": int(hit["entity"]["campaign_id"]),
                "score": float(hit["distance"]),
            }
            for hit in hits
        ]

    async def upsert_anomaly_case_vector(
        self,
        case_id: int,
        scene_vector: list[float],
    ) -> None:
        """写入或更新历史异常案例向量。

        Args:
            case_id: MySQL case_library 案例编号。
            scene_vector: 案例场景的语义向量。

        Returns:
            无返回值。
        """
        client = self._require_client()
        settings = get_settings()

        await to_thread(
            client.upsert,
            collection_name=(
                settings.milvus_anomaly_case_collection
            ),
            data=[
                {
                    "case_id": case_id,
                    "scene_vector": scene_vector,
                }
            ],
        )

    async def search_similar_anomaly_cases(
        self,
        scene_vector: list[float],
        limit: int = 5,
    ) -> list[dict[str, int | float]]:
        """根据异常场景向量召回相似案例。

        Args:
            scene_vector: 当前异常场景的查询向量。
            limit: 最大召回案例数量。

        Returns:
            按相似度排序的案例编号和分数列表。
        """
        client = self._require_client()
        settings = get_settings()

        results = await to_thread(
            client.search,
            collection_name=(
                settings.milvus_anomaly_case_collection
            ),
            data=[scene_vector],
            anns_field="scene_vector",
            limit=limit,
            search_params={
                "metric_type": "COSINE",
                "params": {},
            },
            consistency_level="Strong",
        )

        hits = results[0] if results else []

        return [
            {
                "case_id": int(hit["case_id"]),
                "score": float(hit["distance"]),
            }
            for hit in hits
        ]

    async def upsert_intervention_case_vector(
        self,
        case_id: int,
        intervention_vector: list[float],
    ) -> None:
        """写入或更新历史干预案例向量。

        Args:
            case_id: MySQL case_library 中的案例编号。
            intervention_vector: 历史干预案例的语义向量。

        Returns:
            无返回值。

        Raises:
            RuntimeError: Milvus 客户端尚未初始化。
        """
        client = self._require_client()
        settings = get_settings()

        await to_thread(
            client.upsert,
            collection_name=(
                settings.milvus_intervention_case_collection
            ),
            data=[
                {
                    "case_id": case_id,
                    "intervention_vector": (
                        intervention_vector
                    ),
                }
            ],
        )

    async def search_similar_intervention_cases(
        self,
        intervention_vector: list[float],
        limit: int = 5,
    ) -> list[dict[str, int | float]]:
        """根据当前异常及原因召回相似干预案例。

        Args:
            intervention_vector: 当前异常场景与原因的查询向量。
            limit: 最多召回的案例数量。

        Returns:
            按相似度从高到低排列的案例编号和分数。

        Raises:
            RuntimeError: Milvus 客户端尚未初始化。
        """
        client = self._require_client()
        settings = get_settings()

        results = await to_thread(
            client.search,
            collection_name=(
                settings.milvus_intervention_case_collection
            ),
            data=[intervention_vector],
            anns_field="intervention_vector",
            limit=limit,
            search_params={
                "metric_type": "COSINE",
                "params": {},
            },
            consistency_level="Strong",
        )

        hits = results[0] if results else []

        return [
            {
                "case_id": int(hit["case_id"]),
                "score": float(hit["distance"]),
            }
            for hit in hits
        ]

    def close(self) -> None:
        """关闭客户端连接。

        Returns:
            无返回值。
        """
        if self._client is not None:
            self._client.close()
            self._client = None


milvus_client = MilvusService()

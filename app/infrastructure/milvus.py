from pymilvus import DataType, MilvusClient
from app.core.config import get_settings
from asyncio import to_thread
from pymilvus import DataType,MilvusClient

class MilvusService:
    def __init__(self) -> None:
        self._client: MilvusClient | None = None

    def _require_client(self) -> MilvusClient:
        if self._client is None:
            raise RuntimeError("Milvus client is not initialized")
        return self._client

    def initialize(self) -> None:
        settings = get_settings()
        self._client = MilvusClient(
            uri=settings.milvus_uri, 
            token=settings.milvus_token # type: ignore
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

    def check(self) -> None:
        client = self._require_client()
        client.has_collection(get_settings().milvus_collection) # type: ignore

    async def upsert_strategy_vector(
        self,
        strategy_id:int,
        campaign_id:int,
        goal_vector:list[float],
    ) -> None:
        client = self._require_client()
        settings = get_settings()

        await to_thread(
            client.upsert,
            collection_name=settings.milvus_campaign_strategy_collection,
            data = [
                {
                "strategy_id":strategy_id,
                "campaign_id":campaign_id,
                "goal_vector":goal_vector,
                }
            ],
        )

    async def search_similar_strategies(
        self,
        goal_vector: list[float],
        current_campaign_id: int,
        limit: int = 5,
    ) -> list[dict[str, int | float]]:
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

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


milvus_client = MilvusService()

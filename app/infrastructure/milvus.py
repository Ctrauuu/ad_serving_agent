from pymilvus import MilvusClient

from app.core.config import get_settings


class MilvusService:
    def __init__(self) -> None:
        self._client: MilvusClient | None = None

    def initialize(self) -> None:
        settings = get_settings()
        self._client = MilvusClient(uri=settings.milvus_uri, token=settings.milvus_token) # type: ignore
        if not self._client.has_collection(settings.milvus_collection):
            self._client.create_collection(
                collection_name=settings.milvus_collection,
                dimension=settings.milvus_vector_dim,
            )

    def check(self) -> None:
        if self._client is None:
            raise RuntimeError("Milvus client is not initialized")
        self._client.has_collection(get_settings().milvus_collection) # type: ignore

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


milvus_client = MilvusService()

from functools import lru_cache
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "广告投放执行Agent"
    database_url: str = "mysql+asyncmy://root:password@127.0.0.1:3306/ad_serving_agent"
    redis_url: str = "redis://127.0.0.1:6379/0"
    milvus_uri: str = "http://127.0.0.1:19530"
    milvus_token: str | None = "root:Milvus"
    milvus_collection: str = "ad_knowledge"
    milvus_vector_dim: int = 1024
    jwt_secret_key: SecretStr
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    dashscope_api_key: SecretStr
    dashscope_model: str = "qwen-plus"
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"


@lru_cache
def get_settings() -> Settings:
    return Settings() # type: ignore

from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class CatalogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProductRead(CatalogRead):
    id: int
    name: str
    category: str | None
    selling_points: str | None
    target_audience_desc: str | None
    price: Decimal | None


class ChannelRead(CatalogRead):
    id: int
    name: str
    platform: str
    min_budget_daily: Decimal
    rules: str | None


class AudienceRead(CatalogRead):
    id: int
    name: str
    targeting_desc: str | None
    audience_type: str | None
    estimated_size: int | None


class CreativeRead(CatalogRead):
    id: int
    name: str
    type: str
    url: str | None
    selling_point_tags: str | None
    landing_page_url: str | None
    version: int
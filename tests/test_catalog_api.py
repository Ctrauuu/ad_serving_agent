from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
from app.infrastructure.database import get_session
from app.main import app
from app.models import Audience, Channel, Creative, Product, User


@pytest.fixture
def catalog_session() -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.all.return_value = [
        Product(
            id=1,
            name="智能财税SaaS",
            category="企业服务",
            selling_points="自动记账",
            target_audience_desc="中小企业",
            price=Decimal("1999.00"),
            status="启用",
        )
    ]
    session.scalars.return_value = result

    async def session_override():
        yield session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user] = lambda: User(
        id=2,
        role="增长运营",
        status="启用",
    )

    yield session
    app.dependency_overrides.clear()


def test_product_list_returns_enabled_products(
    catalog_session: AsyncMock,
) -> None:
    response = TestClient(app).get("/api/v1/products")

    assert response.status_code == 200
    assert response.json()["code"] == 0
    assert response.json()["data"][0]["name"] == "智能财税SaaS"

    statement = catalog_session.scalars.await_args.args[0]
    assert "product.status" in str(statement)


def test_product_list_requires_login(
    catalog_session: AsyncMock,
) -> None:
    app.dependency_overrides.pop(get_current_user)

    response = TestClient(app).get("/api/v1/products")

    assert response.status_code == 401
    assert response.json()["code"] == 401

def test_channel_list_returns_enabled_channels(
    catalog_session: AsyncMock,
) -> None:
    catalog_session.scalars.return_value.all.return_value = [
        Channel(
            id=1,
            name="搜索广告",
            platform="百度",
            min_budget_daily=Decimal("100.00"),
            rules="关键词竞价",
            status="启用",
        )
    ]

    response = TestClient(app).get("/api/v1/channels")

    assert response.status_code == 200
    assert response.json()["code"] == 0
    assert response.json()["data"][0]["name"] == "搜索广告"
    assert response.json()["data"][0]["platform"] == "百度"

    statement = catalog_session.scalars.await_args.args[0]
    assert "channel.status" in str(statement)

def test_audience_list_returns_enabled_audiences(
    catalog_session: AsyncMock,
) -> None:
    catalog_session.scalars.return_value.all.return_value = [
        Audience(
            id=1,
            name="中小企业HR负责人",
            targeting_desc="50至200人企业的人力资源负责人",
            audience_type="企业人群",
            estimated_size=100000,
            status="启用",
        )
    ]

    response = TestClient(app).get("/api/v1/audiences")

    assert response.status_code == 200
    assert response.json()["code"] == 0
    assert response.json()["data"][0]["name"] == "中小企业HR负责人"
    assert response.json()["data"][0]["estimated_size"] == 100000

    statement = catalog_session.scalars.await_args.args[0]
    assert "audience.status" in str(statement)

def test_creative_list_returns_approved_creatives(
    catalog_session: AsyncMock,
) -> None:
    catalog_session.scalars.return_value.all.return_value = [
        Creative(
            id=1,
            name="HR系统线索广告",
            type="图片",
            url="https://example.com/creative.png",
            selling_point_tags="自动化,降本增效",
            landing_page_url="https://example.com/hr",
            version=1,
            status="已审核",
        )
    ]

    response = TestClient(app).get("/api/v1/creatives")

    assert response.status_code == 200
    assert response.json()["code"] == 0
    assert response.json()["data"][0]["name"] == "HR系统线索广告"
    assert response.json()["data"][0]["version"] == 1

    statement = catalog_session.scalars.await_args.args[0]
    assert "creative.status" in str(statement)
    assert "已审核" in str(statement.compile().params.values())
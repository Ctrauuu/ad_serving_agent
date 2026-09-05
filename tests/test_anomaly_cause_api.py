from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_user
from app.infrastructure.database import get_session
from app.main import app
from app.models import AnomalyRecord, Campaign, User
from app.schemas import (
    AnomalyCauseRead,
    CauseAnalysisResult,
    CauseEvidence,
    InterventionSuggestionRead,
    SuggestionGenerationResult,
)


@pytest.fixture(autouse=True)
def override_dependencies():
    """替换归因接口的数据库和登录依赖。"""
    session = AsyncMock()

    async def session_override():
        """提供测试数据库会话。"""
        yield session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user] = lambda: User(
        id=7,
        role="投放人员",
        status="启用",
    )
    yield session
    app.dependency_overrides.clear()


def make_anomaly() -> AnomalyRecord:
    """创建接口测试异常记录。"""
    return AnomalyRecord(
        id=4,
        campaign_id=8,
        target_type="ad_group",
        target_id=32,
        anomaly_type="valid_lead_drop",
        metric="valid_lead_rate",
        severity="高",
        status="待归因",
        detected_at=datetime(2026, 9, 4, 12),
    )


def make_result() -> CauseAnalysisResult:
    """创建接口测试归因结果。"""
    return CauseAnalysisResult(
        anomaly_id=4,
        data_sufficient=False,
        has_historical_cases=False,
        causes=[
            AnomalyCauseRead(
                id=11,
                anomaly_id=4,
                cause_type="素材疲劳",
                hypothesis="素材长期投放导致质量下降",
                confidence=Decimal("0.850"),
                evidence_sources=[
                    CauseEvidence(
                        type="creative",
                        ref="creative:1",
                    )
                ],
                data_sufficient=False,
                created_at=datetime(2026, 9, 5, 9),
            )
        ],
    )


def make_suggestion_result() -> SuggestionGenerationResult:
    """创建生成建议接口的测试结果。"""
    now = datetime(2026, 9, 5, 12)
    return SuggestionGenerationResult(
        anomaly_id=4,
        data_sufficient=False,
        has_historical_cases=True,
        suggestions=[
            InterventionSuggestionRead(
                id=21,
                anomaly_id=4,
                campaign_id=8,
                target_type="ad_group",
                target_id=32,
                cause_id=11,
                action_type="extend_observation",
                action_params={
                    "ad_group_id": 32,
                    "hours": 2,
                },
                metric_evidence={"metric": "cost_rate"},
                triggered_rule="消耗速度过快",
                expected_impact={"effect": "补充样本"},
                risk_notes="观察期仍会产生消耗",
                risk_level="低",
                is_primary=True,
                status="待提交",
                created_at=now,
                updated_at=now,
            )
        ],
    )


def test_analyze_cause_returns_unified_result(
    monkeypatch: pytest.MonkeyPatch,
    override_dependencies: AsyncMock,
) -> None:
    """验证触发归因返回统一响应。"""
    override_dependencies.get.return_value = make_anomaly()
    monkeypatch.setattr(
        "app.api.v1.anomalies.get_campaign",
        AsyncMock(return_value=Campaign(id=8, owner_id=7)),
    )
    monkeypatch.setattr(
        "app.api.v1.anomalies.analyze_anomaly_cause",
        AsyncMock(return_value=make_result()),
    )

    response = TestClient(app).post(
        "/api/v1/anomalies/4/cause/analyze"
    )

    assert response.status_code == 200
    assert response.json()["data"]["anomaly_id"] == 4
    assert response.json()["data"]["causes"][0]["cause_type"] == "素材疲劳"


def test_analyze_cause_returns_404_for_missing_anomaly(
    override_dependencies: AsyncMock,
) -> None:
    """验证异常不存在时返回 404。"""
    override_dependencies.get.return_value = None

    response = TestClient(app).post(
        "/api/v1/anomalies/999/cause/analyze"
    )

    assert response.status_code == 404


def test_analyze_cause_hides_inaccessible_anomaly(
    monkeypatch: pytest.MonkeyPatch,
    override_dependencies: AsyncMock,
) -> None:
    """验证不可访问的异常统一表现为不存在。"""
    override_dependencies.get.return_value = make_anomaly()
    analyze = AsyncMock()
    monkeypatch.setattr(
        "app.api.v1.anomalies.get_campaign",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.api.v1.anomalies.analyze_anomaly_cause",
        analyze,
    )

    response = TestClient(app).post(
        "/api/v1/anomalies/4/cause/analyze"
    )

    assert response.status_code == 404
    analyze.assert_not_awaited()


def test_analyze_cause_returns_422_for_invalid_analysis(
    monkeypatch: pytest.MonkeyPatch,
    override_dependencies: AsyncMock,
) -> None:
    """验证归因数据错误转换为 422。"""
    override_dependencies.get.return_value = make_anomaly()
    monkeypatch.setattr(
        "app.api.v1.anomalies.get_campaign",
        AsyncMock(return_value=Campaign(id=8, owner_id=7)),
    )
    monkeypatch.setattr(
        "app.api.v1.anomalies.analyze_anomaly_cause",
        AsyncMock(side_effect=ValueError("模型证据类型不匹配")),
    )

    response = TestClient(app).post(
        "/api/v1/anomalies/4/cause/analyze"
    )

    assert response.status_code == 422
    assert response.json()["message"] == "模型证据类型不匹配"


def test_get_cause_returns_unified_result(
    monkeypatch: pytest.MonkeyPatch,
    override_dependencies: AsyncMock,
) -> None:
    """验证原因查询返回已保存的统一响应。"""
    override_dependencies.get.return_value = make_anomaly()
    monkeypatch.setattr(
        "app.api.v1.anomalies.get_campaign",
        AsyncMock(return_value=Campaign(id=8, owner_id=7)),
    )
    monkeypatch.setattr(
        "app.api.v1.anomalies.get_anomaly_cause_result",
        AsyncMock(return_value=make_result()),
    )

    response = TestClient(app).get(
        "/api/v1/anomalies/4/cause"
    )

    assert response.status_code == 200
    assert response.json()["data"]["causes"][0]["confidence"] == "0.850"


def test_get_cause_returns_404_before_analysis(
    monkeypatch: pytest.MonkeyPatch,
    override_dependencies: AsyncMock,
) -> None:
    """验证异常尚无归因结果时返回 404。"""
    override_dependencies.get.return_value = make_anomaly()
    monkeypatch.setattr(
        "app.api.v1.anomalies.get_campaign",
        AsyncMock(return_value=Campaign(id=8, owner_id=7)),
    )
    monkeypatch.setattr(
        "app.api.v1.anomalies.get_anomaly_cause_result",
        AsyncMock(return_value=None),
    )

    response = TestClient(app).get(
        "/api/v1/anomalies/4/cause"
    )

    assert response.status_code == 404
    assert response.json()["message"] == "异常原因不存在"


def test_get_cause_hides_inaccessible_anomaly(
    monkeypatch: pytest.MonkeyPatch,
    override_dependencies: AsyncMock,
) -> None:
    """验证查询接口不会泄露无权访问的异常。"""
    override_dependencies.get.return_value = make_anomaly()
    get_result = AsyncMock()
    monkeypatch.setattr(
        "app.api.v1.anomalies.get_campaign",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.api.v1.anomalies.get_anomaly_cause_result",
        get_result,
    )

    response = TestClient(app).get(
        "/api/v1/anomalies/4/cause"
    )

    assert response.status_code == 404
    get_result.assert_not_awaited()


def test_generate_suggestions_returns_unified_result(
    monkeypatch: pytest.MonkeyPatch,
    override_dependencies: AsyncMock,
) -> None:
    """验证生成建议接口返回统一响应。"""
    override_dependencies.get.return_value = make_anomaly()
    monkeypatch.setattr(
        "app.api.v1.anomalies.get_campaign",
        AsyncMock(return_value=Campaign(id=8, owner_id=7)),
    )
    monkeypatch.setattr(
        (
            "app.api.v1.anomalies."
            "generate_intervention_suggestions"
        ),
        AsyncMock(return_value=make_suggestion_result()),
    )

    response = TestClient(app).post(
        "/api/v1/anomalies/4/suggestions/generate"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["anomaly_id"] == 4
    assert data["suggestions"][0]["risk_level"] == "低"


def test_generate_suggestions_hides_inaccessible_anomaly(
    monkeypatch: pytest.MonkeyPatch,
    override_dependencies: AsyncMock,
) -> None:
    """验证无权访问的异常不会触发建议生成。"""
    override_dependencies.get.return_value = make_anomaly()
    generate = AsyncMock()
    monkeypatch.setattr(
        "app.api.v1.anomalies.get_campaign",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        (
            "app.api.v1.anomalies."
            "generate_intervention_suggestions"
        ),
        generate,
    )

    response = TestClient(app).post(
        "/api/v1/anomalies/4/suggestions/generate"
    )

    assert response.status_code == 404
    generate.assert_not_awaited()


def test_generate_suggestions_returns_422_for_invalid_context(
    monkeypatch: pytest.MonkeyPatch,
    override_dependencies: AsyncMock,
) -> None:
    """验证建议生成条件错误转换为 422。"""
    override_dependencies.get.return_value = make_anomaly()
    monkeypatch.setattr(
        "app.api.v1.anomalies.get_campaign",
        AsyncMock(return_value=Campaign(id=8, owner_id=7)),
    )
    monkeypatch.setattr(
        (
            "app.api.v1.anomalies."
            "generate_intervention_suggestions"
        ),
        AsyncMock(
            side_effect=ValueError("异常尚未完成原因归因")
        ),
    )

    response = TestClient(app).post(
        "/api/v1/anomalies/4/suggestions/generate"
    )

    assert response.status_code == 422
    assert response.json()["message"] == "异常尚未完成原因归因"


def test_get_suggestions_returns_unified_result(
    monkeypatch: pytest.MonkeyPatch,
    override_dependencies: AsyncMock,
) -> None:
    """验证建议查询接口返回已保存结果。"""
    override_dependencies.get.return_value = make_anomaly()
    monkeypatch.setattr(
        "app.api.v1.anomalies.get_campaign",
        AsyncMock(return_value=Campaign(id=8, owner_id=7)),
    )
    monkeypatch.setattr(
        (
            "app.api.v1.anomalies."
            "get_intervention_suggestion_result"
        ),
        AsyncMock(return_value=make_suggestion_result()),
    )

    response = TestClient(app).get(
        "/api/v1/anomalies/4/suggestions"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["suggestions"][0]["is_primary"] is True


def test_get_suggestions_returns_404_before_generation(
    monkeypatch: pytest.MonkeyPatch,
    override_dependencies: AsyncMock,
) -> None:
    """验证异常尚无建议时查询接口返回 404。"""
    override_dependencies.get.return_value = make_anomaly()
    monkeypatch.setattr(
        "app.api.v1.anomalies.get_campaign",
        AsyncMock(return_value=Campaign(id=8, owner_id=7)),
    )
    monkeypatch.setattr(
        (
            "app.api.v1.anomalies."
            "get_intervention_suggestion_result"
        ),
        AsyncMock(return_value=None),
    )

    response = TestClient(app).get(
        "/api/v1/anomalies/4/suggestions"
    )

    assert response.status_code == 404
    assert response.json()["message"] == "干预建议不存在"


def test_get_suggestions_hides_inaccessible_anomaly(
    monkeypatch: pytest.MonkeyPatch,
    override_dependencies: AsyncMock,
) -> None:
    """验证无权访问时不会查询干预建议。"""
    override_dependencies.get.return_value = make_anomaly()
    get_result = AsyncMock()
    monkeypatch.setattr(
        "app.api.v1.anomalies.get_campaign",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        (
            "app.api.v1.anomalies."
            "get_intervention_suggestion_result"
        ),
        get_result,
    )

    response = TestClient(app).get(
        "/api/v1/anomalies/4/suggestions"
    )

    assert response.status_code == 404
    get_result.assert_not_awaited()

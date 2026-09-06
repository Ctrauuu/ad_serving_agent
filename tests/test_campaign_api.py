from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from app.schemas import GoalParseResult, StructuredGoal
from app.api.dependencies.auth import get_current_user
from app.infrastructure.database import get_session
from app.main import app
from app.models import Campaign, ReviewReport, User


def make_campaign() -> Campaign:
    return Campaign(
        id=8,
        name="新品推广",
        product_id=1,
        owner_id=7,
        budget_total=Decimal("80000.00"),
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
        conversion_goal="线索",
        goal_text="预算8万获取高质量线索",
        structured_goal=None,
        risk_limit=None,
        status="草稿",
        created_at=datetime(2026, 9, 1),
        updated_at=datetime(2026, 9, 1),
    )


@pytest.fixture(autouse=True)
def override_dependencies():
    async def session_override():
        yield object()

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user] = lambda: User(
        id=7,
        role="投放人员",
        status="启用",
    )
    yield
    app.dependency_overrides.clear()


def test_create_campaign_returns_unified_response(monkeypatch) -> None:
    async def fake_create_campaign(session, form, owner_id):
        assert owner_id == 7
        return make_campaign()

    monkeypatch.setattr(
        "app.api.v1.campaigns.create_campaign",
        fake_create_campaign,
    )

    response = TestClient(app).post(
        "/api/v1/campaigns",
        json={
            "name": "新品推广",
            "product_id": 1,
            "budget_total": "80000.00",
            "start_date": "2026-09-01",
            "end_date": "2026-09-30",
            "conversion_goal": "线索",
            "goal_text": "预算8万获取高质量线索",
        },
    )

    assert response.status_code == 201
    assert response.json()["code"] == 0
    assert response.json()["data"]["name"] == "新品推广"
    assert response.json()["data"]["status"] == "草稿"


def test_missing_campaign_returns_404(monkeypatch) -> None:
    async def fake_get_campaign(session, campaign_id, current_user):
        return None

    monkeypatch.setattr(
        "app.api.v1.campaigns.get_campaign",
        fake_get_campaign,
    )

    response = TestClient(app).get("/api/v1/campaigns/999")

    assert response.status_code == 404
    assert response.json() == {
        "code": 404,
        "message": "活动不存在",
        "data": None,
    }


def test_manual_metric_sync_returns_result(monkeypatch) -> None:
    from app.schemas import MetricSyncResult

    campaign = make_campaign()

    async def fake_get_campaign(*_):
        return campaign

    async def fake_sync_metrics(session, selected_campaign):
        assert selected_campaign is campaign
        return MetricSyncResult(
            campaign_id=8,
            status="success",
            synced_groups=2,
            failed_groups=0,
            stale_groups=0,
            metric_rows=12,
            data_time=datetime(2026, 9, 3, 13, 30),
            errors=[],
        )

    monkeypatch.setattr(
        "app.api.v1.campaigns.get_campaign",
        fake_get_campaign,
    )
    monkeypatch.setattr(
        "app.api.v1.campaigns.sync_campaign_metrics",
        fake_sync_metrics,
    )

    response = TestClient(app).post(
        "/api/v1/campaigns/8/metrics/sync"
    )

    assert response.status_code == 200
    assert response.json()["data"]["synced_groups"] == 2


def test_realtime_metrics_rejects_unknown_dimension() -> None:
    response = TestClient(app).get(
        "/api/v1/campaigns/8/metrics/realtime",
        params={"dimension": "unknown"},
    )

    assert response.status_code == 422


def test_metric_trend_rejects_unknown_window() -> None:
    response = TestClient(app).get(
        "/api/v1/campaigns/8/metrics/trend",
        params={"window": "week"},
    )

    assert response.status_code == 422


def test_campaign_budget_returns_redis_state(monkeypatch) -> None:
    from app.schemas import CampaignBudgetResult

    async def fake_get_campaign(*_):
        return make_campaign()

    async def fake_get_campaign_budget(campaign_id):
        return CampaignBudgetResult(
            campaign_id=campaign_id,
            data_time=None,
            is_stale=True,
            items=[],
        )

    monkeypatch.setattr(
        "app.api.v1.campaigns.get_campaign",
        fake_get_campaign,
    )
    monkeypatch.setattr(
        "app.api.v1.campaigns.get_campaign_budget",
        fake_get_campaign_budget,
    )

    response = TestClient(app).get(
        "/api/v1/campaigns/8/budget"
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "campaign_id": 8,
        "data_time": None,
        "is_stale": True,
        "items": [],
    }


def test_manual_anomaly_scan_returns_result(monkeypatch) -> None:
    from app.schemas import AnomalyScanResult

    async def fake_get_campaign(*_):
        return make_campaign()

    async def fake_scan(session, campaign):
        return AnomalyScanResult(
            campaign_id=campaign.id,
            status="completed",
            stage="稳态期",
            scanned_groups=2,
            evaluated_rules=8,
            created_count=1,
            deduplicated_count=0,
            skipped_stale_groups=0,
            skipped_no_data_groups=0,
            created_ids=[9],
            errors=[],
        )

    monkeypatch.setattr(
        "app.api.v1.campaigns.get_campaign",
        fake_get_campaign,
    )
    monkeypatch.setattr(
        "app.api.v1.campaigns.scan_campaign_anomalies",
        fake_scan,
    )

    response = TestClient(app).post(
        "/api/v1/campaigns/8/anomalies/scan"
    )

    assert response.status_code == 200
    assert response.json()["data"]["created_ids"] == [9]


def test_anomaly_list_rejects_unknown_status() -> None:
    response = TestClient(app).get(
        "/api/v1/campaigns/8/anomalies",
        params={"status": "未知状态"},
    )

    assert response.status_code == 422

def test_parse_goal_returns_missing_fields(monkeypatch) -> None:
    async def fake_get_campaign(session, campaign_id, current_user):
        return make_campaign()

    async def fake_parse_goal_text(goal_text):
        return GoalParseResult(
            missing_fields=["audience", "cycle", "risk"]
        )

    monkeypatch.setattr(
        "app.api.v1.campaigns.get_campaign",
        fake_get_campaign,
    )
    monkeypatch.setattr(
        "app.api.v1.campaigns.parse_goal_text",
        fake_parse_goal_text,
    )

    response = TestClient(app).post(
        "/api/v1/campaigns/8/parse-goal"
    )

    assert response.status_code == 422
    assert response.json() == {
        "code": 422,
        "message": "目标信息不完整",
        "data": {
            "missing_fields": ["audience", "cycle", "risk"]
        },
    }


def test_parse_goal_returns_structured_result(monkeypatch) -> None:
    async def fake_get_campaign(session, campaign_id, current_user):
        return make_campaign()

    async def fake_parse_goal_text(goal_text):
        return GoalParseResult(
            structured_goal=StructuredGoal(
                product="企业HR系统",
                audience="企业HR负责人",
                budget=Decimal("80000.00"),
                cycle="2026-09-01 至 2026-09-30",
                conversion_goal="线索",
                channels=["信息流", "搜索广告"],
                risk="单条线索成本不超过300元",
            )
        )

    monkeypatch.setattr(
        "app.api.v1.campaigns.get_campaign",
        fake_get_campaign,
    )
    monkeypatch.setattr(
        "app.api.v1.campaigns.parse_goal_text",
        fake_parse_goal_text,
    )

    response = TestClient(app).post(
        "/api/v1/campaigns/8/parse-goal"
    )

    assert response.status_code == 200
    assert response.json()["code"] == 0
    assert (
        response.json()["data"]["structured_goal"]["product"]
        == "企业HR系统"
    )
    assert response.json()["data"]["missing_fields"] == []


def test_generate_review_returns_new_report(monkeypatch) -> None:
    """验证已结束活动可通过接口生成并返回复盘报告。"""
    campaign = make_campaign()
    campaign.status = "已结束"
    report = ReviewReport(
        id=5,
        campaign_id=8,
        version=2,
        overall_metrics={"cost": 100.0},
        strategy_evaluation={"verdict": "达标"},
        intervention_evaluation={},
        reusable_conclusion="可复用结论",
        lessons="经验",
        improvement="改进",
        generated_at=datetime(2026, 9, 6, 12),
    )

    async def fake_get_campaign(*_):
        return campaign

    async def fake_generate(session, selected_campaign):
        assert selected_campaign is campaign
        return report

    monkeypatch.setattr(
        "app.api.v1.campaigns.get_campaign",
        fake_get_campaign,
    )
    monkeypatch.setattr(
        "app.api.v1.campaigns.generate_campaign_review",
        fake_generate,
    )

    response = TestClient(app).post(
        "/api/v1/campaigns/8/review/generate"
    )

    assert response.status_code == 200
    assert response.json()["data"]["version"] == 2
    assert response.json()["data"]["reusable_conclusion"] == (
        "可复用结论"
    )


def test_generate_review_returns_404_for_missing_campaign(
    monkeypatch,
) -> None:
    """验证复盘接口不泄露不存在或无权活动的信息。"""
    async def fake_get_campaign(*_):
        return None

    monkeypatch.setattr(
        "app.api.v1.campaigns.get_campaign",
        fake_get_campaign,
    )

    response = TestClient(app).post(
        "/api/v1/campaigns/999/review/generate"
    )

    assert response.status_code == 404
    assert response.json()["message"] == "活动不存在"


def test_generate_review_maps_invalid_state_to_422(monkeypatch) -> None:
    """验证服务层活动状态错误会转换为客户端可处理的 422。"""
    campaign = make_campaign()

    async def fake_get_campaign(*_):
        return campaign

    async def fake_generate(*_):
        raise ValueError("活动尚未结束，不能生成复盘")

    monkeypatch.setattr(
        "app.api.v1.campaigns.get_campaign",
        fake_get_campaign,
    )
    monkeypatch.setattr(
        "app.api.v1.campaigns.generate_campaign_review",
        fake_generate,
    )

    response = TestClient(app).post(
        "/api/v1/campaigns/8/review/generate"
    )

    assert response.status_code == 422
    assert response.json()["message"] == "活动尚未结束，不能生成复盘"

def test_confirm_goal_returns_updated_campaign(monkeypatch) -> None:
    async def fake_update_campaign(
        session,
        campaign_id,
        form,
        current_user,
    ):
        campaign = make_campaign()
        campaign.structured_goal = form.structured_goal.model_dump(mode="json")
        campaign.status = "目标已结构化"
        return campaign

    monkeypatch.setattr(
        "app.api.v1.campaigns.update_campaign",
        fake_update_campaign,
    )

    response = TestClient(app).put(
        "/api/v1/campaigns/8",
        json={
            "structured_goal": {
                "product": "企业HR系统",
                "audience": "企业HR负责人",
                "budget": 80000,
                "cycle": "2026年9月",
                "conversion_goal": "线索",
                "channels": ["信息流"],
                "risk": "单条线索成本不超过300元",
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "目标已结构化"
    assert (
        response.json()["data"]["structured_goal"]["product"]
        == "企业HR系统"
    )


def test_only_investor_can_confirm_goal() -> None:
    app.dependency_overrides[get_current_user] = lambda: User(
        id=3,
        role="投放负责人",
        status="启用",
    )

    response = TestClient(app).put(
        "/api/v1/campaigns/8",
        json={
            "structured_goal": {
                "product": "企业HR系统",
                "audience": "企业HR负责人",
                "budget": 80000,
                "cycle": "2026年9月",
                "conversion_goal": "线索",
                "channels": ["信息流"],
                "risk": "单条线索成本不超过300元",
            }
        },
    )

    assert response.status_code == 403
    assert response.json()["message"] == "仅投放人员可以确认结构化目标"


def test_generate_strategy_returns_strategy_and_evidence(
    monkeypatch,
) -> None:
    async def fake_get_campaign(
        session,
        campaign_id,
        current_user,
    ):
        campaign = make_campaign()
        campaign.status = "目标已结构化"
        campaign.structured_goal = {
            "product": "企业HR系统",
            "audience": "企业HR负责人",
            "budget": 80000,
            "cycle": "2026年9月",
            "conversion_goal": "线索",
            "channels": ["信息流"],
            "risk": "单条线索成本不超过300元",
        }
        return campaign

    async def fake_generate_strategy(
        session,
        campaign,
    ):
        return {
            "strategy": {
                "id": 21,
                "campaign_id": campaign.id,
                "version": 1,
                "status": "待确认",
            },
            "evidence": [
                {
                    "evidence_type": "渠道规则",
                    "explanation": (
                        "信息流适合线索获取"
                    ),
                }
            ],
        }

    monkeypatch.setattr(
        "app.api.v1.campaigns.get_campaign",
        fake_get_campaign,
    )
    monkeypatch.setattr(
        "app.api.v1.campaigns.generate_strategy",
        fake_generate_strategy,
    )

    response = TestClient(app).post(
        "/api/v1/campaigns/8/strategy/generate"
    )

    assert response.status_code == 200
    assert response.json()["code"] == 0
    assert (
        response.json()["data"]["strategy"]["version"]
        == 1
    )
    assert (
        response.json()["data"]["evidence"][0][
            "evidence_type"
        ]
        == "渠道规则"
    )

def test_get_strategy_returns_latest_detail(
    monkeypatch,
) -> None:
    async def fake_get_campaign(
        session,
        campaign_id,
        current_user,
    ):
        return make_campaign()

    async def fake_get_latest_strategy(
        session,
        campaign_id,
    ):
        return {
            "strategy": {
                "id": 21,
                "campaign_id": campaign_id,
                "version": 2,
                "status": "待确认",
            },
            "evidence": [
                {
                    "evidence_type": "历史活动",
                    "explanation": "参考历史活动#5",
                }
            ],
        }

    monkeypatch.setattr(
        "app.api.v1.campaigns.get_campaign",
        fake_get_campaign,
    )
    monkeypatch.setattr(
        "app.api.v1.campaigns.get_latest_strategy",
        fake_get_latest_strategy,
    )

    response = TestClient(app).get(
        "/api/v1/campaigns/8/strategy"
    )

    assert response.status_code == 200
    assert response.json()["code"] == 0
    assert (
        response.json()["data"]["strategy"]["version"]
        == 2
    )
    assert (
        response.json()["data"]["evidence"][0][
            "evidence_type"
        ]
        == "历史活动"
    )

def test_only_leader_can_confirm_strategy() -> None:
    response = TestClient(app).post(
        "/api/v1/campaigns/8/strategy/confirm"
    )

    assert response.status_code == 403
    assert response.json()["message"] == "权限不足"


def test_leader_can_confirm_strategy(
    monkeypatch,
) -> None:
    app.dependency_overrides[
        get_current_user
    ] = lambda: User(
        id=3,
        role="投放负责人",
        status="启用",
    )

    async def fake_get_campaign(
        session,
        campaign_id,
        current_user,
    ):
        campaign = make_campaign()
        campaign.status = "策略生成中"
        return campaign

    async def fake_confirm_strategy(
        session,
        campaign,
        confirmed_by,
    ):
        assert confirmed_by == 3

        return {
            "campaign_id": campaign.id,
            "strategy_id": 21,
            "status": "策略已确认",
        }

    monkeypatch.setattr(
        "app.api.v1.campaigns.get_campaign",
        fake_get_campaign,
    )
    monkeypatch.setattr(
        "app.api.v1.campaigns.confirm_strategy",
        fake_confirm_strategy,
    )

    response = TestClient(app).post(
        "/api/v1/campaigns/8/strategy/confirm"
    )

    assert response.status_code == 200
    assert response.json()["code"] == 0
    assert (
        response.json()["data"]["strategy_id"]
        == 21
    )
    assert (
        response.json()["data"]["status"]
        == "策略已确认"
    )


def test_investor_can_create_ad_tasks(monkeypatch) -> None:
    async def fake_get_campaign(
        session,
        campaign_id,
        current_user,
    ):
        campaign = make_campaign()
        campaign.status = "策略已确认"
        return campaign

    async def fake_create_ad_tasks(
        session,
        campaign,
        form,
    ):
        assert form.audience_id == 1
        assert form.creative_id == 1
        assert form.bid == Decimal("5")
        return {
            "campaign_id": campaign.id,
            "status": "投放中",
            "plans": [],
        }

    monkeypatch.setattr(
        "app.api.v1.campaigns.get_campaign",
        fake_get_campaign,
    )
    monkeypatch.setattr(
        "app.api.v1.campaigns.create_ad_tasks",
        fake_create_ad_tasks,
    )

    response = TestClient(app).post(
        "/api/v1/campaigns/8/ad-tasks/create",
        json={
            "audience_id": 1,
            "creative_id": 1,
            "bid": "5.00",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "投放中"


def test_only_investor_can_create_ad_tasks() -> None:
    app.dependency_overrides[get_current_user] = lambda: User(
        id=3,
        role="投放负责人",
        status="启用",
    )

    response = TestClient(app).post(
        "/api/v1/campaigns/8/ad-tasks/create",
        json={
            "audience_id": 1,
            "creative_id": 1,
            "bid": "5.00",
        },
    )

    assert response.status_code == 403
    assert response.json()["message"] == "权限不足"


def test_list_ad_tasks_returns_task_tree(monkeypatch) -> None:
    async def fake_get_campaign(
        session,
        campaign_id,
        current_user,
    ):
        campaign = make_campaign()
        campaign.status = "投放中"
        return campaign

    async def fake_list_ad_tasks(session, campaign):
        return {
            "campaign_id": campaign.id,
            "status": campaign.status,
            "plans": [],
        }

    monkeypatch.setattr(
        "app.api.v1.campaigns.get_campaign",
        fake_get_campaign,
    )
    monkeypatch.setattr(
        "app.api.v1.campaigns.list_ad_tasks",
        fake_list_ad_tasks,
    )

    response = TestClient(app).get(
        "/api/v1/campaigns/8/ad-tasks"
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "campaign_id": 8,
        "status": "投放中",
        "plans": [],
    }


def test_get_review_returns_latest_report(monkeypatch) -> None:
    """验证复盘查询接口返回服务层提供的最新版本。"""
    report = ReviewReport(
        id=5,
        campaign_id=8,
        version=3,
        overall_metrics={},
        strategy_evaluation={},
        intervention_evaluation={},
        generated_at=datetime(2026, 9, 6, 12),
    )

    async def fake_get_campaign(*_):
        return make_campaign()

    async def fake_get_latest_report(session, campaign_id):
        assert campaign_id == 8
        return report

    monkeypatch.setattr(
        "app.api.v1.campaigns.get_campaign",
        fake_get_campaign,
    )
    monkeypatch.setattr(
        "app.api.v1.campaigns.get_latest_review_report",
        fake_get_latest_report,
    )

    response = TestClient(app).get("/api/v1/campaigns/8/review")

    assert response.status_code == 200
    assert response.json()["data"]["version"] == 3


def test_get_review_returns_404_when_report_absent(monkeypatch) -> None:
    """验证活动存在但尚未复盘时返回明确的 404。"""
    async def fake_get_campaign(*_):
        return make_campaign()

    async def fake_get_latest_report(*_):
        return None

    monkeypatch.setattr(
        "app.api.v1.campaigns.get_campaign",
        fake_get_campaign,
    )
    monkeypatch.setattr(
        "app.api.v1.campaigns.get_latest_review_report",
        fake_get_latest_report,
    )

    response = TestClient(app).get("/api/v1/campaigns/8/review")

    assert response.status_code == 404
    assert response.json()["message"] == "复盘报告不存在"


def test_get_review_returns_404_when_campaign_absent(monkeypatch) -> None:
    """验证无权或不存在活动时不会查询或泄露复盘内容。"""
    async def fake_get_campaign(*_):
        return None

    monkeypatch.setattr(
        "app.api.v1.campaigns.get_campaign",
        fake_get_campaign,
    )

    response = TestClient(app).get("/api/v1/campaigns/999/review")

    assert response.status_code == 404
    assert response.json()["message"] == "活动不存在"

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ActionExecution,
    AdMetricRealtime,
    AnomalyCause,
    AnomalyRecord,
    Campaign,
    CaseLibrary,
    KnowledgeDoc,
    ReviewReport,
    Strategy,
)
from app.schemas import ReviewCaseCandidate, ReviewGenerationOutput
from app.services.review import (
    evaluate_strategy_metrics,
    evaluate_action_effect,
    collect_review_context,
    get_action_effect_windows,
    get_action_window_metrics,
    get_intervention_evaluations,
    get_latest_confirmed_strategy,
    get_review_anomalies,
    get_overall_metrics,
    get_latest_review_report,
    generate_review_narrative,
    generate_campaign_review,
    index_review_cases,
    list_review_cases,
    save_review_cases,
    save_review_report,
    upsert_review_knowledge_doc,
)


def make_campaign_day_metric(
    *,
    impression: int,
    click: int,
    cost: str,
    lead: int,
    valid_lead: int,
    order: int,
    roi: str | None,
) -> AdMetricRealtime:
    """构造活动日指标汇总测试使用的一条记录。

    Args:
        impression: 曝光数。
        click: 点击数。
        cost: 消耗金额。
        lead: 线索数。
        valid_lead: 有效线索数。
        order: 订单数。
        roi: 该日 ROI；None 表示收入未知。

    Returns:
        活动维度的日粒度指标记录。
    """
    return AdMetricRealtime(
        campaign_id=8,
        dimension="campaign",
        dim_id=8,
        time_window="day",
        impression=impression,
        click=click,
        cost=Decimal(cost),
        lead=lead,
        valid_lead=valid_lead,
        order=order,
        roi=Decimal(roi) if roi is not None else None,
    )


def make_ad_group_hour_metric(
    *,
    cost: str,
    lead: int,
    valid_lead: int,
) -> AdMetricRealtime:
    """构造广告组小时窗口测试使用的指标记录。

    Args:
        cost: 小时消耗金额。
        lead: 小时线索数。
        valid_lead: 小时有效线索数。

    Returns:
        广告组维度的小时粒度指标记录。
    """
    return AdMetricRealtime(
        campaign_id=8,
        dimension="ad_group",
        dim_id=32,
        time_window="hour",
        impression=100,
        click=10,
        cost=Decimal(cost),
        lead=lead,
        valid_lead=valid_lead,
        order=0,
        roi=Decimal("1"),
    )


@pytest.mark.asyncio
async def test_get_overall_metrics_recalculates_from_daily_totals() -> None:
    """验证复盘汇总按日指标累计并重新计算比例。"""
    session = AsyncMock(spec=AsyncSession)
    session.scalars.return_value = iter(
        [
            make_campaign_day_metric(
                impression=1000,
                click=100,
                cost="100",
                lead=10,
                valid_lead=5,
                order=1,
                roi="2",
            ),
            make_campaign_day_metric(
                impression=1000,
                click=50,
                cost="300",
                lead=10,
                valid_lead=10,
                order=2,
                roi="1",
            ),
        ]
    )

    result = await get_overall_metrics(session, 8)

    assert result == {
        "data_days": 2,
        "impression": 2000,
        "click": 150,
        "cost": 400.0,
        "lead": 20,
        "valid_lead": 15,
        "order": 3,
        "ctr": 0.075,
        "cpc": 2.67,
        "cpa": 20.0,
        "valid_lead_rate": 0.75,
        "roi": 1.25,
    }
    sql = str(session.scalars.await_args.args[0])
    assert "ad_metric_realtime.dimension =" in sql
    assert "ad_metric_realtime.time_window =" in sql


@pytest.mark.asyncio
async def test_get_overall_metrics_returns_empty_data_shape() -> None:
    """验证没有日指标时返回可明确标注数据不足的结果。"""
    session = AsyncMock(spec=AsyncSession)
    session.scalars.return_value = iter(())

    result = await get_overall_metrics(session, 8)

    assert result == {
        "data_days": 0,
        "impression": 0,
        "click": 0,
        "cost": 0.0,
        "lead": 0,
        "valid_lead": 0,
        "order": 0,
        "ctr": None,
        "cpc": None,
        "cpa": None,
        "valid_lead_rate": None,
        "roi": None,
    }


def test_evaluate_strategy_metrics_handles_directions_and_rates() -> None:
    """验证策略评价按指标方向比较并标准化百分比预期。"""
    result = evaluate_strategy_metrics(
        {
            "cpa": 25,
            "ctr": 2.8,
            "valid_lead_rate": 0.42,
            "cost_rate_daily": 300,
            "cvr_search": 0.12,
        },
        {
            "data_days": 2,
            "impression": 2000,
            "click": 150,
            "cost": 400.0,
            "lead": 20,
            "valid_lead": 8,
            "order": 3,
            "ctr": 0.035,
            "cpc": 2.67,
            "cpa": 20.0,
            "valid_lead_rate": 0.4,
            "roi": 1.25,
        },
    )

    assert result["verdict"] == "部分达标"
    assert result["met_count"] == 3
    assert result["unmet_count"] == 1
    assert result["unavailable_count"] == 1
    assert result["metrics"]["cpa"]["status"] == "达标"
    assert result["metrics"]["ctr"] == {
        "expected": 0.028,
        "actual": 0.035,
        "difference": 0.007,
        "difference_rate": 0.25,
        "direction": "越高越好",
        "status": "达标",
    }
    assert result["metrics"]["valid_lead_rate"]["status"] == (
        "未达标"
    )
    assert result["metrics"]["cvr_search"] == {
        "expected": 0.12,
        "actual": None,
        "status": "数据不足",
        "reason": "当前没有可比实际指标",
    }


def test_evaluate_strategy_metrics_handles_missing_expectations() -> None:
    """验证没有策略预期时不生成虚假的评价结论。"""
    result = evaluate_strategy_metrics(
        None,
        {
            "data_days": 0,
            "click": 0,
            "lead": 0,
            "cost": 0.0,
            "cpa": None,
            "cpc": None,
            "ctr": None,
            "valid_lead_rate": None,
            "roi": None,
        },
    )

    assert result == {
        "verdict": "无预期指标",
        "met_count": 0,
        "unmet_count": 0,
        "unavailable_count": 0,
        "metrics": {},
    }


def test_action_effect_windows_uses_complete_hours() -> None:
    """验证非整点动作跳过不完整小时，整点动作不跳过。"""
    assert get_action_effect_windows(
        datetime(2026, 9, 6, 13, 20),
    ) == (
        datetime(2026, 9, 6, 11),
        datetime(2026, 9, 6, 13),
        datetime(2026, 9, 6, 14),
        datetime(2026, 9, 6, 16),
    )
    assert get_action_effect_windows(
        datetime(2026, 9, 6, 13),
    ) == (
        datetime(2026, 9, 6, 11),
        datetime(2026, 9, 6, 13),
        datetime(2026, 9, 6, 13),
        datetime(2026, 9, 6, 15),
    )


@pytest.mark.asyncio
async def test_get_action_window_metrics_summarizes_complete_windows() -> None:
    """验证动作前后两小时指标使用各自窗口累计值。"""
    action = ActionExecution(
        id=6,
        campaign_id=8,
        target_type="ad_group",
        target_id=32,
        executed_at=datetime(2026, 9, 6, 13, 20),
    )
    session = AsyncMock(spec=AsyncSession)
    session.scalars.side_effect = [
        iter(
            [
                make_ad_group_hour_metric(
                    cost="100",
                    lead=1,
                    valid_lead=1,
                ),
                make_ad_group_hour_metric(
                    cost="100",
                    lead=1,
                    valid_lead=1,
                ),
            ]
        ),
        iter(
            [
                make_ad_group_hour_metric(
                    cost="50",
                    lead=2,
                    valid_lead=2,
                ),
                make_ad_group_hour_metric(
                    cost="50",
                    lead=2,
                    valid_lead=2,
                ),
            ]
        ),
    ]

    result = await get_action_window_metrics(session, action)

    assert result["before"]["data_sufficient"] is True
    assert result["before"]["cost"] == 200.0
    assert result["before"]["cpa"] == 100.0
    assert result["after"]["data_sufficient"] is True
    assert result["after"]["cost"] == 100.0
    assert result["after"]["cpa"] == 25.0
    assert result["after"]["window_start"] == (
        "2026-09-06T14:00:00"
    )
    assert session.scalars.await_count == 2


@pytest.mark.asyncio
async def test_get_action_window_metrics_marks_missing_hours() -> None:
    """验证任一窗口缺少小时指标时明确标记数据不足。"""
    action = ActionExecution(
        id=6,
        campaign_id=8,
        target_type="ad_group",
        target_id=32,
        executed_at=datetime(2026, 9, 6, 13),
    )
    session = AsyncMock(spec=AsyncSession)
    session.scalars.side_effect = [
        iter(
            [
                make_ad_group_hour_metric(
                    cost="100",
                    lead=1,
                    valid_lead=1,
                ),
            ]
        ),
        iter(()),
    ]

    result = await get_action_window_metrics(session, action)

    assert result["before"]["data_hours"] == 1
    assert result["before"]["data_sufficient"] is False
    assert result["after"]["data_hours"] == 0
    assert result["after"]["data_sufficient"] is False


def make_window_metrics(
    *,
    before_cpa: float | None,
    after_cpa: float | None,
    before_valid_lead_rate: float | None,
    after_valid_lead_rate: float | None,
    before_roi: float | None,
    after_roi: float | None,
    data_sufficient: bool,
) -> dict[str, object]:
    """构造动作效果评价测试使用的前后窗口指标。

    Args:
        before_cpa: 动作前 CPA。
        after_cpa: 动作后 CPA。
        before_valid_lead_rate: 动作前有效线索率。
        after_valid_lead_rate: 动作后有效线索率。
        before_roi: 动作前 ROI。
        after_roi: 动作后 ROI。
        data_sufficient: 两个窗口是否都具备完整小时数据。

    Returns:
        符合 get_action_window_metrics 返回形态的测试字典。
    """
    return {
        "before": {
            "cost": 200.0,
            "cpa": before_cpa,
            "valid_lead_rate": before_valid_lead_rate,
            "roi": before_roi,
            "data_sufficient": data_sufficient,
        },
        "after": {
            "cost": 100.0,
            "cpa": after_cpa,
            "valid_lead_rate": after_valid_lead_rate,
            "roi": after_roi,
            "data_sufficient": data_sufficient,
        },
    }


def test_evaluate_action_effect_marks_quality_improvement() -> None:
    """验证 CPA 降低且质量指标提升时评价为改善。"""
    action = ActionExecution(
        id=6,
        action_type="replace_creative",
        target_id=32,
    )

    result = evaluate_action_effect(
        action,
        make_window_metrics(
            before_cpa=100,
            after_cpa=25,
            before_valid_lead_rate=0.2,
            after_valid_lead_rate=0.4,
            before_roi=1,
            after_roi=2,
            data_sufficient=True,
        ),
    )

    assert result["verdict"] == "改善"
    assert result["changes"]["cpa"]["difference"] == -75.0
    assert result["changes"]["roi"]["change_rate"] == 1.0


def test_evaluate_action_effect_marks_quality_deterioration() -> None:
    """验证质量指标全部恶化时评价为恶化。"""
    action = ActionExecution(
        id=6,
        action_type="adjust_bid",
        target_id=32,
    )

    result = evaluate_action_effect(
        action,
        make_window_metrics(
            before_cpa=100,
            after_cpa=120,
            before_valid_lead_rate=0.4,
            after_valid_lead_rate=0.2,
            before_roi=2,
            after_roi=1,
            data_sufficient=True,
        ),
    )

    assert result["verdict"] == "恶化"


def test_evaluate_action_effect_refuses_incomplete_windows() -> None:
    """验证缺少完整小时窗口时不判断动作效果。"""
    action = ActionExecution(
        id=6,
        action_type="pause",
        target_id=32,
    )

    result = evaluate_action_effect(
        action,
        make_window_metrics(
            before_cpa=100,
            after_cpa=25,
            before_valid_lead_rate=0.2,
            after_valid_lead_rate=0.4,
            before_roi=1,
            after_roi=2,
            data_sufficient=False,
        ),
    )

    assert result["data_sufficient"] is False
    assert result["verdict"] == "数据不足"


@pytest.mark.asyncio
async def test_get_intervention_evaluations_isolates_action_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证单条动作取数失败不会中断其他动作复盘。"""
    successful_action = ActionExecution(
        id=6,
        campaign_id=8,
        target_type="ad_group",
        target_id=32,
        action_type="pause",
        status="成功",
        executed_at=datetime(2026, 9, 6, 13),
    )
    invalid_action = ActionExecution(
        id=7,
        campaign_id=8,
        target_type="ad_group",
        target_id=33,
        action_type="adjust_bid",
        status="成功",
        executed_at=None,
    )
    session = AsyncMock(spec=AsyncSession)
    session.scalars.return_value = iter(
        [successful_action, invalid_action]
    )

    async def get_windows(
        session: AsyncSession,
        action: ActionExecution,
    ) -> dict[str, object]:
        """为第一条动作返回窗口，为第二条模拟取数异常。"""
        if action.id == 7:
            raise ValueError("动作缺少执行时间，无法评估效果")
        return make_window_metrics(
            before_cpa=100,
            after_cpa=25,
            before_valid_lead_rate=0.2,
            after_valid_lead_rate=0.4,
            before_roi=1,
            after_roi=2,
            data_sufficient=True,
        )

    monkeypatch.setattr(
        "app.services.review.get_action_window_metrics",
        get_windows,
    )

    result = await get_intervention_evaluations(session, 8)

    assert result["action_6"]["verdict"] == "改善"
    assert result["action_7"] == {
        "action_id": 7,
        "action_type": "adjust_bid",
        "target_id": 33,
        "data_sufficient": False,
        "verdict": "数据不足",
        "reason": "动作缺少执行时间，无法评估效果",
    }
    assert "action_execution.status" in str(
        session.scalars.await_args.args[0]
    )


@pytest.mark.asyncio
async def test_get_latest_confirmed_strategy_uses_latest_version() -> None:
    """验证复盘只读取版本最高的已确认策略。"""
    strategy = Strategy(
        id=3,
        campaign_id=8,
        version=2,
        status="已确认",
        expected_metrics={"cpa": 260},
    )
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = strategy

    result = await get_latest_confirmed_strategy(session, 8)

    assert result is strategy
    sql = str(session.scalar.await_args.args[0])
    assert "strategy.status =" in sql
    assert "ORDER BY strategy.version DESC" in sql


@pytest.mark.asyncio
async def test_get_review_anomalies_skips_cause_query_when_empty() -> None:
    """验证活动无异常时不额外查询原因假设。"""
    session = AsyncMock(spec=AsyncSession)
    session.scalars.return_value = iter(())

    result = await get_review_anomalies(session, 8)

    assert result == []
    assert session.scalars.await_count == 1


@pytest.mark.asyncio
async def test_get_review_anomalies_groups_causes_by_anomaly() -> None:
    """验证异常原因按异常归属并保留置信度排序结果。"""
    first = AnomalyRecord(
        id=4,
        campaign_id=8,
        target_type="ad_group",
        target_id=32,
        anomaly_type="cpa_spike",
        metric="cpa",
        metric_value=Decimal("300"),
        baseline_value=Decimal("180"),
        severity="高",
        status="已归因",
        evidence_json={"cost": 300},
        detected_at=datetime(2026, 9, 6, 10),
    )
    second = AnomalyRecord(
        id=5,
        campaign_id=8,
        target_type="ad_group",
        target_id=33,
        anomaly_type="valid_lead_drop",
        metric="valid_lead_rate",
        metric_value=Decimal("0.2"),
        baseline_value=Decimal("0.4"),
        severity="中",
        status="待归因",
        evidence_json=None,
        detected_at=datetime(2026, 9, 6, 11),
    )
    high_confidence = AnomalyCause(
        id=8,
        anomaly_id=4,
        cause_type="素材",
        hypothesis="素材疲劳",
        confidence=Decimal("0.900"),
        evidence_sources=[{"type": "data"}],
        data_sufficient=True,
    )
    lower_confidence = AnomalyCause(
        id=9,
        anomaly_id=4,
        cause_type="人群",
        hypothesis="人群过宽",
        confidence=Decimal("0.600"),
        evidence_sources=None,
        data_sufficient=False,
    )
    session = AsyncMock(spec=AsyncSession)
    session.scalars.side_effect = [
        iter([first, second]),
        iter([high_confidence, lower_confidence]),
    ]

    result = await get_review_anomalies(session, 8)

    assert result[0]["metric_value"] == 300.0
    assert result[0]["causes"] == [
        {
            "id": 8,
            "cause_type": "素材",
            "hypothesis": "素材疲劳",
            "confidence": 0.9,
            "evidence_sources": [{"type": "data"}],
            "data_sufficient": True,
        },
        {
            "id": 9,
            "cause_type": "人群",
            "hypothesis": "人群过宽",
            "confidence": 0.6,
            "evidence_sources": [],
            "data_sufficient": False,
        },
    ]
    assert result[1]["causes"] == []
    cause_sql = str(session.scalars.await_args_list[1].args[0])
    assert "anomaly_cause.confidence DESC" in cause_sql


@pytest.mark.asyncio
async def test_collect_review_context_combines_all_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证复盘上下文汇总确定性指标、策略、异常和动作结果。"""
    strategy = Strategy(
        id=3,
        campaign_id=8,
        version=2,
        status="已确认",
        channel_mix=[{"channel_name": "搜索"}],
        budget_split={"搜索": 1000},
        expected_metrics={"cpa": 260},
        risk_notes="观察 CPA",
    )
    overall = {
        "data_days": 2,
        "impression": 2000,
        "click": 150,
        "cost": 400.0,
        "lead": 20,
        "valid_lead": 10,
        "order": 3,
        "ctr": 0.075,
        "cpc": 2.67,
        "cpa": 20.0,
        "valid_lead_rate": 0.5,
        "roi": 1.25,
    }
    monkeypatch.setattr(
        "app.services.review.get_overall_metrics",
        AsyncMock(return_value=overall),
    )
    monkeypatch.setattr(
        "app.services.review.get_latest_confirmed_strategy",
        AsyncMock(return_value=strategy),
    )
    monkeypatch.setattr(
        "app.services.review.get_review_anomalies",
        AsyncMock(return_value=[{"id": 4, "causes": []}]),
    )
    monkeypatch.setattr(
        "app.services.review.get_intervention_evaluations",
        AsyncMock(return_value={"action_6": {"verdict": "改善"}}),
    )

    context = await collect_review_context(
        AsyncMock(spec=AsyncSession),
        8,
    )

    assert context["campaign_id"] == 8
    assert context["overall_metrics"] is overall
    assert context["strategy"] == {
        "id": 3,
        "version": 2,
        "channel_mix": [{"channel_name": "搜索"}],
        "budget_split": {"搜索": 1000},
        "expected_metrics": {"cpa": 260},
        "risk_notes": "观察 CPA",
    }
    assert context["strategy_evaluation"]["verdict"] == "达标"
    assert context["anomalies"] == [{"id": 4, "causes": []}]
    assert context["interventions"] == {
        "action_6": {"verdict": "改善"}
    }


@pytest.mark.asyncio
async def test_collect_review_context_degrades_without_strategy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证没有确认策略时仍能构造复盘上下文。"""
    overall = {
        "data_days": 0,
        "click": 0,
        "lead": 0,
        "cost": 0.0,
        "cpa": None,
        "cpc": None,
        "ctr": None,
        "valid_lead_rate": None,
        "roi": None,
    }
    monkeypatch.setattr(
        "app.services.review.get_overall_metrics",
        AsyncMock(return_value=overall),
    )
    monkeypatch.setattr(
        "app.services.review.get_latest_confirmed_strategy",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.services.review.get_review_anomalies",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "app.services.review.get_intervention_evaluations",
        AsyncMock(return_value={}),
    )

    context = await collect_review_context(
        AsyncMock(spec=AsyncSession),
        8,
    )

    assert context["strategy"] is None
    assert context["strategy_evaluation"]["verdict"] == "无预期指标"


@pytest.mark.asyncio
async def test_generate_review_narrative_parses_model_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证复盘模型结果会被解析为受约束的案例输出。"""
    llm = AsyncMock()
    llm.ainvoke.return_value = SimpleNamespace(
        content="""
        {
          "reusable_conclusion": "搜索渠道可用于高意图线索获取。",
          "lessons": "素材疲劳应提前处理。",
          "improvement": "每周更新一次素材。",
          "cases": [
            {
              "case_type": "strategy",
              "scene_desc": "企业服务线索投放。",
              "anomaly_type": null,
              "cause": null,
              "action": null,
              "effectiveness": "有效",
              "conclusion": "搜索渠道 CPA 达标。"
            }
          ]
        }
        """
    )
    monkeypatch.setattr(
        "app.services.review.get_goal_llm",
        lambda: llm,
    )

    result = await generate_review_narrative(
        {"campaign_id": 8, "strategy_evaluation": {}}
    )

    assert result.cases[0].case_type == "strategy"
    assert llm.ainvoke.await_count == 1


@pytest.mark.asyncio
async def test_generate_review_narrative_rejects_non_text_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证模型未返回文本时不会继续解析或写入错误结果。"""
    llm = AsyncMock()
    llm.ainvoke.return_value = SimpleNamespace(content=["not text"])
    monkeypatch.setattr(
        "app.services.review.get_goal_llm",
        lambda: llm,
    )

    with pytest.raises(ValueError, match="未返回文本"):
        await generate_review_narrative({"campaign_id": 8})


@pytest.mark.asyncio
async def test_generate_review_narrative_rejects_invalid_structure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证不符合案例 schema 的模型结果会被拒绝。"""
    llm = AsyncMock()
    llm.ainvoke.return_value = SimpleNamespace(content='{"cases": []}')
    monkeypatch.setattr(
        "app.services.review.get_goal_llm",
        lambda: llm,
    )

    with pytest.raises(ValueError, match="不符合复盘结构"):
        await generate_review_narrative({"campaign_id": 8})


@pytest.mark.asyncio
async def test_save_review_report_increments_version() -> None:
    """验证重复复盘会新增版本而不覆盖已有报告。"""
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = 2
    context = {
        "overall_metrics": {"cost": 100.0},
        "strategy_evaluation": {"verdict": "达标"},
        "interventions": {"action_1": {"verdict": "改善"}},
    }
    narrative = ReviewGenerationOutput.model_validate(
        {
            "reusable_conclusion": "结论",
            "lessons": "经验",
            "improvement": "改进",
            "cases": [
                {
                    "case_type": "strategy",
                    "scene_desc": "场景",
                    "effectiveness": "有效",
                    "conclusion": "结论",
                }
            ],
        }
    )

    report = await save_review_report(
        session,
        8,
        context,
        narrative,
    )

    assert report.version == 3
    assert report.overall_metrics == {"cost": 100.0}
    assert report.intervention_evaluation == {
        "action_1": {"verdict": "改善"}
    }
    assert session.add.call_args.args[0] is report
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_latest_review_report_returns_highest_version() -> None:
    """验证查询按版本倒序读取最新复盘报告。"""
    session = AsyncMock(spec=AsyncSession)
    latest = SimpleNamespace(id=7, version=3)
    session.scalar.return_value = latest

    result = await get_latest_review_report(session, 8)

    assert result is latest
    sql = str(session.scalar.await_args.args[0])
    assert "review_report.version DESC" in sql


@pytest.mark.asyncio
async def test_save_review_cases_reuses_same_campaign_scene() -> None:
    """验证重复复盘更新相同案例而不会持续新增重复记录。"""
    existing = CaseLibrary(
        id=4,
        case_type="strategy",
        campaign_id=8,
        scene_desc="企业服务线索投放",
        effectiveness="失败",
        conclusion="旧结论",
    )
    session = AsyncMock(spec=AsyncSession)
    session.scalars.return_value = iter([existing])
    candidates = [
        ReviewCaseCandidate(
            case_type="strategy",
            scene_desc="企业服务线索投放",
            effectiveness="有效",
            conclusion="更新结论",
        ),
        ReviewCaseCandidate(
            case_type="anomaly",
            scene_desc="CPA 连续升高",
            anomaly_type="成本飙升",
            cause="素材疲劳",
            effectiveness="失败",
            conclusion="应提前换素材",
        ),
        ReviewCaseCandidate(
            case_type="anomaly",
            scene_desc="CPA 连续升高",
            anomaly_type="成本飙升",
            cause="素材疲劳",
            effectiveness="失败",
            conclusion="更新后的结论",
        ),
    ]

    saved = await save_review_cases(session, 8, candidates)

    assert saved == [existing, saved[1]]
    assert existing.effectiveness == "有效"
    assert existing.conclusion == "更新结论"
    assert saved[1].conclusion == "更新后的结论"
    assert session.add.call_count == 1
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_index_review_cases_maps_each_type_to_its_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证三类案例写入各自的 Milvus 集合并回写向量标识。"""
    strategy_case = CaseLibrary(
        id=11,
        case_type="strategy",
        campaign_id=8,
        scene_desc="企业服务线索投放",
        effectiveness="有效",
    )
    anomaly_case = CaseLibrary(
        id=12,
        case_type="anomaly",
        campaign_id=8,
        scene_desc="CPA 上升",
        effectiveness="失败",
    )
    intervention_case = CaseLibrary(
        id=13,
        case_type="intervention",
        campaign_id=8,
        scene_desc="换素材后 CPA 下降",
        effectiveness="有效",
    )
    session = AsyncMock(spec=AsyncSession)
    session.get.return_value = SimpleNamespace(
        structured_goal={
            "product": "HR 系统",
            "audience": "HR 负责人",
            "budget": 80000,
            "cycle": "2026-09-01 至 2026-09-30",
            "conversion_goal": "线索",
            "channels": ["搜索"],
            "risk": "CPA 不超过 300 元",
        }
    )
    strategy = Strategy(id=3, campaign_id=8, status="已确认")
    embed_goal_mock = AsyncMock(return_value=[0.1])
    embed_text_mock = AsyncMock(side_effect=[[0.2], [0.3]])
    strategy_upsert = AsyncMock()
    anomaly_upsert = AsyncMock()
    intervention_upsert = AsyncMock()
    monkeypatch.setattr(
        "app.services.review.get_latest_confirmed_strategy",
        AsyncMock(return_value=strategy),
    )
    monkeypatch.setattr(
        "app.services.review.embed_goal",
        embed_goal_mock,
    )
    monkeypatch.setattr(
        "app.services.review.embed_text",
        embed_text_mock,
    )
    monkeypatch.setattr(
        "app.services.review.milvus_client.upsert_strategy_vector",
        strategy_upsert,
    )
    monkeypatch.setattr(
        "app.services.review.milvus_client.upsert_anomaly_case_vector",
        anomaly_upsert,
    )
    monkeypatch.setattr(
        "app.services.review.milvus_client.upsert_intervention_case_vector",
        intervention_upsert,
    )

    await index_review_cases(
        session,
        8,
        [strategy_case, anomaly_case, intervention_case],
    )

    strategy_upsert.assert_awaited_once_with(
        strategy_id=3,
        campaign_id=8,
        goal_vector=[0.1],
    )
    anomaly_upsert.assert_awaited_once_with(
        case_id=12,
        scene_vector=[0.2],
    )
    intervention_upsert.assert_awaited_once_with(
        case_id=13,
        intervention_vector=[0.3],
    )
    assert strategy_case.vector_id == "3"
    assert anomaly_case.vector_id == "12"
    assert intervention_case.vector_id == "13"
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_upsert_review_knowledge_doc_creates_and_indexes_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证新复盘生成一份知识文档及同编号的向量。"""
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
    )
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None
    added: list[KnowledgeDoc] = []
    session.add.side_effect = added.append

    async def assign_document_id() -> None:
        """模拟数据库 flush 后给新增文档分配主键。"""
        if added and added[0].id is None:
            added[0].id = 41

    session.flush.side_effect = assign_document_id
    embed_mock = AsyncMock(return_value=[0.4])
    upsert_mock = AsyncMock()
    monkeypatch.setattr(
        "app.services.review.embed_text",
        embed_mock,
    )
    monkeypatch.setattr(
        "app.services.review.milvus_client.upsert_knowledge_vector",
        upsert_mock,
    )

    document = await upsert_review_knowledge_doc(session, report)

    assert document.id == 41
    assert document.source_ref == "review_report:5"
    assert document.chunk_count == 1
    assert document.parse_status == "已完成"
    assert document.ragflow_doc_id == "41"
    upsert_mock.assert_awaited_once_with(
        knowledge_doc_id=41,
        vector=[0.4],
    )
    assert session.flush.await_count == 2


@pytest.mark.asyncio
async def test_upsert_review_knowledge_doc_reuses_source_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证同一复盘重试更新已有知识文档而不再插入新记录。"""
    report = ReviewReport(
        id=5,
        campaign_id=8,
        version=2,
        overall_metrics={},
        strategy_evaluation={},
        intervention_evaluation={},
    )
    document = KnowledgeDoc(
        id=41,
        title="旧标题",
        doc_type="old",
        source_ref="review_report:5",
        chunk_count=0,
        parse_status="待解析",
    )
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = document
    upsert_mock = AsyncMock()
    monkeypatch.setattr(
        "app.services.review.embed_text",
        AsyncMock(return_value=[0.5]),
    )
    monkeypatch.setattr(
        "app.services.review.milvus_client.upsert_knowledge_vector",
        upsert_mock,
    )

    result = await upsert_review_knowledge_doc(session, report)

    assert result is document
    assert document.title == "活动 8 投放复盘 v2"
    assert document.doc_type == "review_report"
    assert document.chunk_count == 1
    session.add.assert_not_called()
    upsert_mock.assert_awaited_once_with(
        knowledge_doc_id=41,
        vector=[0.5],
    )


@pytest.mark.asyncio
async def test_generate_campaign_review_runs_full_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证已结束活动按顺序生成报告、案例和知识索引后提交。"""
    campaign = Campaign(id=8, status="已结束")
    session = AsyncMock(spec=AsyncSession)
    context = {"campaign_id": 8}
    narrative = ReviewGenerationOutput.model_validate(
        {
            "reusable_conclusion": "结论",
            "lessons": "经验",
            "improvement": "改进",
            "cases": [
                {
                    "case_type": "strategy",
                    "scene_desc": "场景",
                    "effectiveness": "有效",
                    "conclusion": "结论",
                }
            ],
        }
    )
    report = ReviewReport(id=5, campaign_id=8, version=1)
    cases = [
        CaseLibrary(
            id=11,
            case_type="strategy",
            campaign_id=8,
            scene_desc="场景",
            effectiveness="有效",
        )
    ]
    collect_mock = AsyncMock(return_value=context)
    narrative_mock = AsyncMock(return_value=narrative)
    save_report_mock = AsyncMock(return_value=report)
    save_cases_mock = AsyncMock(return_value=cases)
    index_mock = AsyncMock()
    knowledge_mock = AsyncMock()
    monkeypatch.setattr(
        "app.services.review.collect_review_context",
        collect_mock,
    )
    monkeypatch.setattr(
        "app.services.review.generate_review_narrative",
        narrative_mock,
    )
    monkeypatch.setattr(
        "app.services.review.save_review_report",
        save_report_mock,
    )
    monkeypatch.setattr(
        "app.services.review.save_review_cases",
        save_cases_mock,
    )
    monkeypatch.setattr(
        "app.services.review.index_review_cases",
        index_mock,
    )
    monkeypatch.setattr(
        "app.services.review.upsert_review_knowledge_doc",
        knowledge_mock,
    )

    result = await generate_campaign_review(session, campaign)

    assert result is report
    collect_mock.assert_awaited_once_with(session, 8)
    narrative_mock.assert_awaited_once_with(context)
    save_cases_mock.assert_awaited_once_with(
        session,
        8,
        narrative.cases,
    )
    index_mock.assert_awaited_once_with(session, 8, cases)
    knowledge_mock.assert_awaited_once_with(session, report)
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(report)
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_campaign_review_rejects_unfinished_campaign() -> None:
    """验证活动未结束时不会生成复盘或调用外部依赖。"""
    session = AsyncMock(spec=AsyncSession)
    campaign = Campaign(id=8, status="投放中")

    with pytest.raises(ValueError, match="尚未结束"):
        await generate_campaign_review(session, campaign)

    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_campaign_review_rolls_back_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证模型或索引失败时，报告与案例数据库写入会被回滚。"""
    session = AsyncMock(spec=AsyncSession)
    campaign = Campaign(id=8, status="已结束")
    monkeypatch.setattr(
        "app.services.review.collect_review_context",
        AsyncMock(return_value={"campaign_id": 8}),
    )
    monkeypatch.setattr(
        "app.services.review.generate_review_narrative",
        AsyncMock(side_effect=RuntimeError("模型失败")),
    )

    with pytest.raises(RuntimeError, match="模型失败"):
        await generate_campaign_review(session, campaign)

    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_review_cases_optionally_filters_by_type() -> None:
    """验证案例列表按创建时间排序，并可用类型缩小结果集。"""
    cases = [
        CaseLibrary(
            id=2,
            case_type="anomaly",
            scene_desc="CPA 上升",
            effectiveness="失败",
        )
    ]
    session = AsyncMock(spec=AsyncSession)
    session.scalars.return_value = iter(cases)

    result = await list_review_cases(session, "anomaly")

    assert result == cases
    sql = str(session.scalars.await_args.args[0])
    assert "case_library.case_type" in sql
    assert "case_library.created_at DESC" in sql

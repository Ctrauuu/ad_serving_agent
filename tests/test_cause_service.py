import json
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AdGroup,
    AdMetricRealtime,
    AdPlan,
    AnomalyCause,
    AnomalyRecord,
    Audience,
    CaseLibrary,
    Channel,
    Creative,
    SalesFeedback,
)
from app.schemas import CauseEvidence, CauseHypothesis
from app.services.cause import (
    analyze_anomaly_cause,
    build_evidence_catalog,
    collect_attribution_signals,
    format_anomaly_scene,
    generate_cause_hypotheses,
    get_anomaly_cause_result,
    retrieve_similar_cases,
)


def make_anomaly(
    target_type: str = "ad_group",
) -> AnomalyRecord:
    """创建归因信号测试异常。

    Args:
        target_type: 异常目标类型。

    Returns:
        测试异常记录。
    """
    return AnomalyRecord(
        id=7,
        campaign_id=8,
        target_type=target_type,
        target_id=31,
        anomaly_type="valid_lead_drop",
        metric="valid_lead_rate",
        metric_value=Decimal("0.1000"),
        baseline_value=Decimal("0.2700"),
        severity="高",
        evidence_json={"stage": "稳态期"},
        status="待归因",
        detected_at=datetime(2026, 9, 4, 12, 0),
    )


def make_session(
    feedbacks: list[SalesFeedback],
    *,
    include_creative: bool = True,
) -> AsyncMock:
    """创建包含广告信号的模拟数据库会话。

    Args:
        feedbacks: 销售反馈列表。
        include_creative: 是否提供素材。

    Returns:
        配置完成的异步数据库会话替身。
    """
    session = AsyncMock(spec=AsyncSession)
    group = AdGroup(
        id=31,
        campaign_id=8,
        ad_plan_id=21,
        audience_id=1,
        creative_id=1 if include_creative else None,
        name="测试广告组",
        bid=Decimal("30"),
        budget_daily=Decimal("1000"),
        status="已上线",
    )
    objects = {
        AdGroup: group,
        AdPlan: AdPlan(id=21, channel_id=1),
        Channel: Channel(
            id=1,
            name="信息流",
            platform="mock",
            rules="按转化出价",
        ),
        Audience: Audience(
            id=1,
            name="HR负责人",
        ),
        Creative: (
            Creative(
                id=1,
                name="痛点视频",
                type="视频",
                version=1,
                status="已审核",
                created_at=datetime(2026, 8, 10),
            )
            if include_creative
            else None
        ),
    }

    async def fake_get(
        model: type[object],
        object_id: int,
    ) -> object | None:
        """按模型返回对应测试对象。"""
        return objects.get(model)

    session.get.side_effect = fake_get
    session.scalar.return_value = AdMetricRealtime(
        campaign_id=8,
        dimension="ad_group",
        dim_id=31,
        time_window="hour",
        window_start=datetime(2026, 9, 4, 11),
        impression=1000,
        click=60,
        cost=Decimal("1300"),
        lead=10,
        valid_lead=1,
        order=0,
        ctr=None,
        cpc=None,
        cpa=Decimal("130"),
        roi=None,
        collected_at=datetime(2026, 9, 4, 12),
    )
    result = MagicMock()
    result.all.return_value = feedbacks
    session.scalars.return_value = result
    return session


@pytest.mark.asyncio
async def test_collect_signals_marks_recent_feedback_sufficient() -> None:
    """验证三条近期反馈会被标记为数据充分。"""
    anomaly = make_anomaly()
    feedbacks = [
        SalesFeedback(
            campaign_id=8,
            ad_group_id=31,
            lead_id=f"lead_{index}",
            lead_quality="有效" if index == 0 else "无效",
            feedback_at=anomaly.detected_at - timedelta(hours=index),
        )
        for index in range(3)
    ]

    signals, sufficient = await collect_attribution_signals(
        make_session(feedbacks),
        anomaly,
    )

    assert sufficient is True
    assert signals["sales_feedback"]["recent_count"] == 3
    assert "lead_id" not in json.dumps(signals, ensure_ascii=False)
    assert signals["creative"]["running_days"] == 25
    assert signals["metric_snapshot"]["ctr"] is None


@pytest.mark.asyncio
async def test_collect_signals_handles_missing_feedback_and_creative() -> None:
    """验证缺少反馈和素材时返回不足而非报错。"""
    signals, sufficient = await collect_attribution_signals(
        make_session([], include_creative=False),
        make_anomaly(),
    )

    assert sufficient is False
    assert signals["creative"] is None
    assert signals["landing_page"] is None


@pytest.mark.asyncio
async def test_collect_signals_rejects_unsupported_target() -> None:
    """验证当前只接受广告组级异常。"""
    with pytest.raises(ValueError, match="暂不支持"):
        await collect_attribution_signals(
            AsyncMock(spec=AsyncSession),
            make_anomaly("campaign"),
        )


def test_format_anomaly_scene_is_stable() -> None:
    """验证相同信号产生稳定且可读的场景文本。"""
    first = format_anomaly_scene({"metric": 1, "type": "CPA"})
    second = format_anomaly_scene({"type": "CPA", "metric": 1})

    assert first == second
    assert first.startswith("异常归因场景：")


@pytest.mark.asyncio
async def test_retrieve_similar_cases_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 Milvus 无命中时不查询案例详情。"""
    session = AsyncMock(spec=AsyncSession)
    monkeypatch.setattr(
        "app.services.cause.embed_text",
        AsyncMock(return_value=[0.1] * 1024),
    )
    monkeypatch.setattr(
        (
            "app.services.cause.milvus_client."
            "search_similar_anomaly_cases"
        ),
        AsyncMock(return_value=[]),
    )

    cases = await retrieve_similar_cases(session, "场景")

    assert cases == []
    session.scalars.assert_not_awaited()


@pytest.mark.asyncio
async def test_retrieve_similar_cases_preserves_vector_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证召回顺序被保留且失效案例会被跳过。"""
    session = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.all.return_value = [
        CaseLibrary(
            id=1,
            case_type="intervention",
            scene_desc="消耗过快",
            cause="素材疲劳",
            effectiveness="有效",
        ),
        CaseLibrary(
            id=3,
            case_type="anomaly",
            scene_desc="线索率下降",
            cause="人群过宽",
            effectiveness="有效",
        ),
    ]
    session.scalars.return_value = result
    monkeypatch.setattr(
        "app.services.cause.embed_text",
        AsyncMock(return_value=[0.1] * 1024),
    )
    monkeypatch.setattr(
        (
            "app.services.cause.milvus_client."
            "search_similar_anomaly_cases"
        ),
        AsyncMock(
            return_value=[
                {"case_id": 3, "score": 0.9},
                {"case_id": 999, "score": 0.8},
                {"case_id": 1, "score": 0.7},
            ]
        ),
    )

    cases = await retrieve_similar_cases(session, "场景")

    assert [case["case_id"] for case in cases] == [3, 1]


def make_model_causes(
    first_ref: str = "anomaly:7",
    first_type: str = "anomaly",
) -> str:
    """生成大模型归因测试 JSON。

    Args:
        first_ref: 第一条假设引用的证据编号。
        first_type: 第一条假设引用的证据类型。

    Returns:
        符合归因外层结构的 JSON 文本。
    """
    return json.dumps(
        {
            "causes": [
                {
                    "cause_type": "数据波动",
                    "hypothesis": "指标出现短时波动",
                    "confidence": 0.6,
                    "evidence_sources": [
                        {
                            "type": first_type,
                            "ref": first_ref,
                        }
                    ],
                },
                {
                    "cause_type": "素材疲劳",
                    "hypothesis": "素材长期投放导致质量下降",
                    "confidence": 0.9,
                    "evidence_sources": [
                        {
                            "type": "creative",
                            "ref": "creative:1",
                        }
                    ],
                },
            ]
        },
        ensure_ascii=False,
    )


def patch_cause_llm(
    monkeypatch: pytest.MonkeyPatch,
    content: str,
) -> AsyncMock:
    """安装返回指定内容的大模型替身。

    Args:
        monkeypatch: Pytest 属性替换工具。
        content: 模拟模型返回文本。

    Returns:
        模拟的异步模型调用方法。
    """
    ainvoke = AsyncMock(
        return_value=SimpleNamespace(content=content)
    )
    monkeypatch.setattr(
        "app.services.cause.get_goal_llm",
        lambda: SimpleNamespace(ainvoke=ainvoke),
    )
    return ainvoke


@pytest.mark.asyncio
async def test_generate_causes_validates_and_sorts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证归因假设经过证据校验并按置信度排序。"""
    patch_cause_llm(monkeypatch, make_model_causes())
    signals = {
        "anomaly": {"ref": "anomaly:7"},
        "creative": {"ref": "creative:1"},
    }

    causes = await generate_cause_hypotheses(
        signals,
        cases=[],
        data_sufficient=False,
    )

    assert [cause.confidence for cause in causes] == [
        Decimal("0.9"),
        Decimal("0.6"),
    ]


@pytest.mark.asyncio
async def test_generate_causes_rejects_unknown_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证模型不能引用输入中不存在的证据。"""
    patch_cause_llm(
        monkeypatch,
        make_model_causes(first_ref="case:999", first_type="case"),
    )

    with pytest.raises(ValueError, match="不存在的证据"):
        await generate_cause_hypotheses(
            {
                "anomaly": {"ref": "anomaly:7"},
                "creative": {"ref": "creative:1"},
            },
            cases=[],
            data_sufficient=False,
        )


@pytest.mark.asyncio
async def test_generate_causes_rejects_wrong_evidence_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证证据编号与证据类型必须匹配。"""
    patch_cause_llm(
        monkeypatch,
        make_model_causes(
            first_ref="creative:1",
            first_type="metric",
        ),
    )

    with pytest.raises(ValueError, match="类型不匹配"):
        await generate_cause_hypotheses(
            {
                "anomaly": {"ref": "anomaly:7"},
                "creative": {"ref": "creative:1"},
            },
            cases=[],
            data_sufficient=False,
        )


def test_build_evidence_catalog_includes_cases() -> None:
    """验证当前信号与历史案例共同组成证据白名单。"""
    catalog = build_evidence_catalog(
        {"channel": {"ref": "channel:1"}},
        [{"ref": "case:3"}],
    )

    assert catalog == {
        "channel:1": "channel",
        "case:3": "case",
    }


@pytest.mark.asyncio
async def test_analyze_cause_replaces_results_and_updates_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证完整归因替换旧结果并更新异常状态。"""
    session = AsyncMock(spec=AsyncSession)
    anomaly = make_anomaly()
    session.get.return_value = anomaly
    hypotheses = [
        CauseHypothesis(
            cause_type="素材疲劳",
            hypothesis="素材长期投放导致质量下降",
            confidence=Decimal("0.8765"),
            evidence_sources=[
                CauseEvidence(
                    type="creative",
                    ref="creative:1",
                )
            ],
        ),
        CauseHypothesis(
            cause_type="人群过宽",
            hypothesis="目标人群范围过宽",
            confidence=Decimal("0.600"),
            evidence_sources=[
                CauseEvidence(
                    type="audience",
                    ref="audience:1",
                )
            ],
        ),
    ]
    monkeypatch.setattr(
        "app.services.cause.collect_attribution_signals",
        AsyncMock(return_value=({"anomaly": {}}, False)),
    )
    monkeypatch.setattr(
        "app.services.cause.retrieve_similar_cases",
        AsyncMock(return_value=[{"ref": "case:1"}]),
    )
    monkeypatch.setattr(
        "app.services.cause.generate_cause_hypotheses",
        AsyncMock(return_value=hypotheses),
    )

    next_id = 100

    async def fake_refresh(record: AnomalyCause) -> None:
        """模拟数据库补齐主键和创建时间。"""
        nonlocal next_id
        record.id = next_id
        record.created_at = datetime(2026, 9, 5, 9)
        next_id += 1

    session.refresh.side_effect = fake_refresh

    result = await analyze_anomaly_cause(session, anomaly.id)

    assert result is not None
    assert result.has_historical_cases is True
    assert result.data_sufficient is False
    assert anomaly.status == "已归因"
    assert anomaly.evidence_json["cause_analysis"] == {
        "data_sufficient": False,
        "has_historical_cases": True,
    }
    records = session.add_all.call_args.args[0]
    assert len(records) == 2
    assert records[0].confidence == Decimal("0.876")
    assert "DELETE FROM anomaly_cause" in str(
        session.execute.await_args.args[0]
    )
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_analyze_cause_rolls_back_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证归因任一步失败都会回滚事务。"""
    session = AsyncMock(spec=AsyncSession)
    session.get.return_value = make_anomaly()
    monkeypatch.setattr(
        "app.services.cause.collect_attribution_signals",
        AsyncMock(side_effect=ValueError("信号错误")),
    )

    with pytest.raises(ValueError, match="信号错误"):
        await analyze_anomaly_cause(session, 7)

    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_anomaly_cause_result_reads_metadata() -> None:
    """验证已有归因按异常元数据构造查询结果。"""
    session = AsyncMock(spec=AsyncSession)
    anomaly = make_anomaly()
    anomaly.evidence_json = {
        "cause_analysis": {
            "data_sufficient": False,
            "has_historical_cases": False,
        }
    }
    session.get.return_value = anomaly
    result = MagicMock()
    result.all.return_value = [
        AnomalyCause(
            id=11,
            anomaly_id=7,
            cause_type="反馈延迟",
            hypothesis="销售反馈尚未回传",
            confidence=Decimal("0.450"),
            evidence_sources=[
                {
                    "type": "sales_feedback",
                    "ref": "sales_feedback:campaign:8:ad_group:31",
                }
            ],
            data_sufficient=False,
            created_at=datetime(2026, 9, 5, 9),
        )
    ]
    session.scalars.return_value = result

    cause_result = await get_anomaly_cause_result(session, 7)

    assert cause_result is not None
    assert cause_result.has_historical_cases is False
    assert cause_result.causes[0].cause_type == "反馈延迟"

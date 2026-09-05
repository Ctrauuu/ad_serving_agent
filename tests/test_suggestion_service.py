import json
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.milvus import milvus_client
from app.models import (
    AnomalyCause,
    AnomalyRecord,
    CaseLibrary,
    InterventionSuggestion,
)
from app.schemas import SuggestionCandidate
from app.services.suggestion import (
    filter_conflicting_suggestions,
    format_intervention_case,
    format_suggestion_scene,
    generate_intervention_suggestions,
    generate_suggestion_candidates,
    get_suggestion_generation_context,
    get_intervention_suggestion_result,
    grade_suggestion_risk,
    retrieve_similar_intervention_cases,
    save_generated_suggestions,
    validate_conservative_primary,
)


def make_candidate(
    action_type: str,
    is_primary: bool,
) -> SuggestionCandidate:
    """构造风险策略测试使用的候选建议。

    Args:
        action_type: 待测试的动作类型。
        is_primary: 是否为主建议。

    Returns:
        通过 Schema 校验的候选建议。
    """
    return SuggestionCandidate.model_validate(
        {
            "cause_id": 1,
            "action_type": action_type,
            "action_params": {},
            "metric_evidence": {"cpa": "430"},
            "triggered_rule": "CPA 高于动态基线",
            "expected_impact": {"effect": "降低 CPA"},
            "risk_notes": "可能影响线索数量",
            "is_primary": is_primary,
        }
    )


def test_format_intervention_case_contains_retrieval_fields() -> None:
    """验证历史干预案例文本包含场景、原因、动作和效果。"""
    case = CaseLibrary(
        id=1,
        case_type="intervention",
        scene_desc="CPA 持续升高",
        anomaly_type="cost_spike",
        cause="素材疲劳",
        action="replace_creative",
        effectiveness="有效",
        conclusion="更换素材后 CPA 恢复",
    )

    text = format_intervention_case(case)
    payload = json.loads(text.split("\n", 1)[1])

    assert payload["scene"] == "CPA 持续升高"
    assert payload["cause"] == "素材疲劳"
    assert payload["action"] == "replace_creative"
    assert payload["effectiveness"] == "有效"


def test_format_suggestion_scene_sorts_causes_by_confidence() -> None:
    """验证当前场景文本按原因置信度从高到低排列。"""
    anomaly = AnomalyRecord(
        id=4,
        campaign_id=5,
        target_type="ad_group",
        target_id=11,
        anomaly_type="cost_spike",
        metric="cpa",
        metric_value=Decimal("430"),
        baseline_value=Decimal("300"),
        severity="高",
        evidence_json={"stage": "稳态期"},
        status="已归因",
    )
    causes = [
        AnomalyCause(
            id=2,
            anomaly_id=4,
            cause_type="audience",
            hypothesis="人群过窄",
            confidence=Decimal("0.600"),
            data_sufficient=False,
        ),
        AnomalyCause(
            id=1,
            anomaly_id=4,
            cause_type="creative",
            hypothesis="素材疲劳",
            confidence=Decimal("0.900"),
            data_sufficient=False,
        ),
    ]

    text = format_suggestion_scene(anomaly, causes)
    payload = json.loads(text.split("\n", 1)[1])

    assert payload["anomaly"]["metric_value"] == "430"
    assert [
        cause["hypothesis"]
        for cause in payload["causes"]
    ] == ["素材疲劳", "人群过窄"]


@pytest.mark.asyncio
async def test_retrieve_intervention_cases_preserves_match_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证召回结果忽略失效 ID 并保持向量相似度顺序。"""
    session = AsyncMock(spec=AsyncSession)
    scalar_result = MagicMock()
    scalar_result.all.return_value = [
        CaseLibrary(
            id=1,
            case_type="intervention",
            scene_desc="素材疲劳",
            action="replace_creative",
            effectiveness="有效",
        ),
        CaseLibrary(
            id=2,
            case_type="intervention",
            scene_desc="消耗过快",
            action="pause",
            effectiveness="有效",
        ),
    ]
    session.scalars.return_value = scalar_result
    embed = AsyncMock(return_value=[0.1] * 1024)
    search = AsyncMock(
        return_value=[
            {"case_id": 2, "score": 0.92},
            {"case_id": 999, "score": 0.90},
            {"case_id": 1, "score": 0.85},
        ]
    )
    monkeypatch.setattr(
        "app.services.suggestion.embed_text",
        embed,
    )
    monkeypatch.setattr(
        milvus_client,
        "search_similar_intervention_cases",
        search,
    )

    cases = await retrieve_similar_intervention_cases(
        session,
        "当前异常场景",
        limit=3,
    )

    embed.assert_awaited_once_with(
        "当前异常场景",
        text_type="query",
    )
    assert [case["case_id"] for case in cases] == [2, 1]
    assert cases[0]["score"] == 0.92


@pytest.mark.parametrize(
    ("action_type", "expected"),
    [
        ("pause", "高"),
        ("adjust_budget", "高"),
        ("replace_creative", "中"),
        ("extend_observation", "低"),
    ],
)
def test_grade_suggestion_risk(
    action_type: str,
    expected: str,
) -> None:
    """验证动作类型映射到固定风险等级。"""
    candidate = make_candidate(action_type, True)

    assert (
        grade_suggestion_risk(candidate.action_type)
        == expected
    )


def test_insufficient_data_requires_conservative_primary() -> None:
    """验证数据不足时拒绝非保守的主建议。"""
    validate_conservative_primary(
        [make_candidate("extend_observation", True)],
        data_sufficient=False,
    )

    with pytest.raises(
        ValueError,
        match="主建议必须为",
    ):
        validate_conservative_primary(
            [make_candidate("pause", True)],
            data_sufficient=False,
        )

    validate_conservative_primary(
        [make_candidate("pause", True)],
        data_sufficient=True,
    )


def test_filter_suggestions_keeps_primary_and_removes_conflicts() -> None:
    """验证主建议优先并过滤重复动作和互斥动作。"""
    suggestions = [
        make_candidate("pause", False),
        make_candidate("adjust_budget", True),
        make_candidate("adjust_budget", False),
        make_candidate("replace_creative", False),
    ]

    filtered = filter_conflicting_suggestions(suggestions)

    assert [item.action_type for item in filtered] == [
        "adjust_budget",
        "replace_creative",
    ]
    assert filtered[0].is_primary is True

    with pytest.raises(ValueError, match="至少需要"):
        filter_conflicting_suggestions(
            [
                make_candidate("pause", True),
                make_candidate("adjust_budget", False),
            ]
        )


def make_generation_context() -> tuple[
    AnomalyRecord,
    list[AnomalyCause],
]:
    """构造模型生成测试所需的异常和原因。

    Returns:
        一个异常记录及其原因假设列表。
    """
    anomaly = AnomalyRecord(
        id=4,
        campaign_id=8,
        target_type="ad_group",
        target_id=32,
        anomaly_type="cost_rate_fast",
        metric="cost_rate",
        metric_value=Decimal("208.33"),
        baseline_value=Decimal("31.25"),
        severity="高",
        evidence_json={"rule_name": "消耗速度过快"},
        status="已归因",
    )
    cause = AnomalyCause(
        id=8,
        anomaly_id=4,
        cause_type="creative",
        hypothesis="素材疲劳导致低质量流量增加",
        confidence=Decimal("0.800"),
        evidence_sources=[
            {
                "type": "anomaly",
                "ref": "anomaly:4",
            }
        ],
        data_sufficient=True,
    )
    return anomaly, [cause]


def make_model_payload(
    primary_action: str = "pause",
    primary_cause_id: int = 8,
) -> dict[str, object]:
    """构造模型建议 JSON 测试数据。

    Args:
        primary_action: 主建议动作类型。
        primary_cause_id: 主建议引用的原因编号。

    Returns:
        包含主建议和备选建议的模型输出字典。
    """
    first = make_candidate(
        primary_action,
        True,
    ).model_dump(mode="json")
    second = make_candidate(
        "replace_creative",
        False,
    ).model_dump(mode="json")
    first["cause_id"] = primary_cause_id
    second["cause_id"] = 8
    return {"suggestions": [first, second]}


def mock_suggestion_llm(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
) -> MagicMock:
    """替换建议生成模型并返回调用记录对象。

    Args:
        monkeypatch: Pytest 属性替换工具。
        payload: 模拟模型返回的 JSON 数据。

    Returns:
        带异步 ainvoke 方法的模型替身。
    """
    llm = MagicMock()
    llm.ainvoke = AsyncMock(
        return_value=SimpleNamespace(
            content=json.dumps(payload)
        )
    )
    monkeypatch.setattr(
        "app.services.suggestion.get_goal_llm",
        lambda: llm,
    )
    return llm


@pytest.mark.asyncio
async def test_generate_candidates_uses_chat_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证模型结构化结果可以转换为候选建议。"""
    anomaly, causes = make_generation_context()
    llm = mock_suggestion_llm(
        monkeypatch,
        make_model_payload(),
    )

    suggestions = await generate_suggestion_candidates(
        anomaly,
        causes,
        cases=[],
        data_sufficient=True,
    )

    assert [item.action_type for item in suggestions] == [
        "pause",
        "replace_creative",
    ]
    messages = llm.ainvoke.await_args.args[0]
    assert len(messages) == 2


@pytest.mark.asyncio
async def test_generate_candidates_rejects_unknown_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证模型不能引用当前异常以外的原因编号。"""
    anomaly, causes = make_generation_context()
    mock_suggestion_llm(
        monkeypatch,
        make_model_payload(primary_cause_id=999),
    )

    with pytest.raises(ValueError, match="不存在的原因"):
        await generate_suggestion_candidates(
            anomaly,
            causes,
            cases=[],
            data_sufficient=True,
        )


@pytest.mark.asyncio
async def test_generate_candidates_requires_safe_primary_when_insufficient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证归因数据不足时拒绝高风险主建议。"""
    anomaly, causes = make_generation_context()
    mock_suggestion_llm(
        monkeypatch,
        make_model_payload(),
    )

    with pytest.raises(ValueError, match="主建议必须为"):
        await generate_suggestion_candidates(
            anomaly,
            causes,
            cases=[],
            data_sufficient=False,
        )


def make_context_session(
    anomaly: AnomalyRecord | None,
    causes: list[AnomalyCause] | None = None,
    statuses: list[str] | None = None,
) -> AsyncMock:
    """构造建议上下文查询使用的数据库会话。

    Args:
        anomaly: 查询返回的异常记录。
        causes: 查询返回的原因列表。
        statuses: 已有建议状态列表。

    Returns:
        配置好查询结果的异步会话替身。
    """
    session = AsyncMock(spec=AsyncSession)
    session.get.return_value = anomaly
    cause_result = MagicMock()
    cause_result.all.return_value = causes or []
    status_result = MagicMock()
    status_result.all.return_value = statuses or []
    session.scalars.side_effect = [
        cause_result,
        status_result,
    ]
    return session


@pytest.mark.asyncio
async def test_generation_context_returns_valid_data() -> None:
    """验证已归因异常返回原因和数据充分性。"""
    anomaly, causes = make_generation_context()
    causes[0].data_sufficient = False
    session = make_context_session(anomaly, causes)

    result = await get_suggestion_generation_context(
        session,
        anomaly.id,
    )

    assert result is not None
    saved_anomaly, saved_causes, data_sufficient = result
    assert saved_anomaly.id == anomaly.id
    assert saved_causes == causes
    assert data_sufficient is False


@pytest.mark.asyncio
async def test_generation_context_returns_none_when_missing() -> None:
    """验证异常不存在时上下文查询返回 None。"""
    session = make_context_session(None)

    result = await get_suggestion_generation_context(
        session,
        999,
    )

    assert result is None
    session.scalars.assert_not_awaited()


@pytest.mark.asyncio
async def test_generation_context_requires_attribution() -> None:
    """验证尚未归因的异常不能生成建议。"""
    anomaly, _ = make_generation_context()
    anomaly.status = "待归因"
    session = make_context_session(anomaly)

    with pytest.raises(ValueError, match="尚未完成"):
        await get_suggestion_generation_context(
            session,
            anomaly.id,
        )


@pytest.mark.asyncio
async def test_generation_context_requires_causes() -> None:
    """验证没有原因假设的异常不能生成建议。"""
    anomaly, _ = make_generation_context()
    session = make_context_session(anomaly)

    with pytest.raises(ValueError, match="原因不存在"):
        await get_suggestion_generation_context(
            session,
            anomaly.id,
        )


@pytest.mark.asyncio
async def test_generation_context_protects_approved_suggestions() -> None:
    """验证已进入审批流程的建议不能被重新生成覆盖。"""
    anomaly, causes = make_generation_context()
    session = make_context_session(
        anomaly,
        causes,
        statuses=["审批中"],
    )

    with pytest.raises(ValueError, match="不允许重新生成"):
        await get_suggestion_generation_context(
            session,
            anomaly.id,
        )


@pytest.mark.asyncio
async def test_save_suggestions_uses_authoritative_target_and_risk() -> None:
    """验证建议落库使用真实目标、规则和后端风险等级。"""
    anomaly, _ = make_generation_context()
    primary = make_candidate("pause", True)
    primary.cause_id = 8
    primary.action_params = {
        "ad_group_id": 999,
        "campaign_id": 999,
        "reason": "停止异常消耗",
    }
    alternative = make_candidate(
        "replace_creative",
        False,
    )
    alternative.cause_id = 8
    session = AsyncMock(spec=AsyncSession)

    records = await save_generated_suggestions(
        session,
        anomaly,
        [primary, alternative],
        data_sufficient=False,
        has_historical_cases=False,
    )

    assert len(records) == 2
    assert records[0].action_params == {
        "reason": "停止异常消耗",
        "ad_group_id": 32,
    }
    assert records[0].risk_level == "高"
    assert records[1].risk_level == "中"
    assert records[0].triggered_rule == "消耗速度过快"
    assert records[0].status == "待提交"
    assert (
        records[0].metric_evidence["historical_case_notice"]
        == "无历史干预案例参考"
    )
    session.execute.assert_awaited_once()
    session.add_all.assert_called_once_with(records)
    session.flush.assert_awaited_once()


def make_saved_suggestion() -> InterventionSuggestion:
    """构造完整生成结果转换所需的已保存建议。

    Returns:
        包含主键和时间字段的干预建议 ORM 对象。
    """
    now = datetime(2026, 9, 5, 12, 0)
    return InterventionSuggestion(
        id=101,
        anomaly_id=4,
        campaign_id=8,
        target_type="ad_group",
        target_id=32,
        cause_id=8,
        action_type="extend_observation",
        action_params={"ad_group_id": 32, "hours": 2},
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


@pytest.mark.asyncio
async def test_generate_intervention_suggestions_commits_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证完整生成链路保存结果并提交事务。"""
    anomaly, causes = make_generation_context()
    context = AsyncMock(
        return_value=(anomaly, causes, False)
    )
    retrieve = AsyncMock(
        return_value=[{"case_id": 1, "score": 0.8}]
    )
    candidates = [
        make_candidate("extend_observation", True),
        make_candidate("replace_creative", False),
    ]
    generate = AsyncMock(return_value=candidates)
    records = [make_saved_suggestion()]
    save = AsyncMock(return_value=records)
    monkeypatch.setattr(
        "app.services.suggestion.get_suggestion_generation_context",
        context,
    )
    monkeypatch.setattr(
        "app.services.suggestion.retrieve_similar_intervention_cases",
        retrieve,
    )
    monkeypatch.setattr(
        "app.services.suggestion.generate_suggestion_candidates",
        generate,
    )
    monkeypatch.setattr(
        "app.services.suggestion.save_generated_suggestions",
        save,
    )
    session = AsyncMock(spec=AsyncSession)

    result = await generate_intervention_suggestions(
        session,
        anomaly.id,
    )

    assert result is not None
    assert result.has_historical_cases is True
    assert result.data_sufficient is False
    assert result.suggestions[0].id == 101
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(records[0])
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_intervention_suggestions_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证召回或生成失败时事务被回滚。"""
    anomaly, causes = make_generation_context()
    monkeypatch.setattr(
        "app.services.suggestion.get_suggestion_generation_context",
        AsyncMock(return_value=(anomaly, causes, True)),
    )
    monkeypatch.setattr(
        "app.services.suggestion.retrieve_similar_intervention_cases",
        AsyncMock(side_effect=RuntimeError("Milvus 不可用")),
    )
    session = AsyncMock(spec=AsyncSession)

    with pytest.raises(RuntimeError, match="Milvus 不可用"):
        await generate_intervention_suggestions(
            session,
            anomaly.id,
        )

    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_suggestion_result_restores_metadata() -> None:
    """验证查询服务恢复建议及生成时的元数据。"""
    anomaly, _ = make_generation_context()
    record = make_saved_suggestion()
    record.metric_evidence = {
        "metric": "cost_rate",
        "data_sufficient": True,
        "historical_case_notice": None,
    }
    session = AsyncMock(spec=AsyncSession)
    session.get.return_value = anomaly
    result = MagicMock()
    result.all.return_value = [record]
    session.scalars.return_value = result

    response = await get_intervention_suggestion_result(
        session,
        anomaly.id,
    )

    assert response is not None
    assert response.data_sufficient is True
    assert response.has_historical_cases is True
    assert response.suggestions[0].id == record.id


@pytest.mark.asyncio
async def test_get_suggestion_result_returns_none_when_empty() -> None:
    """验证没有已保存建议时查询服务返回 None。"""
    anomaly, _ = make_generation_context()
    session = AsyncMock(spec=AsyncSession)
    session.get.return_value = anomaly
    result = MagicMock()
    result.all.return_value = []
    session.scalars.return_value = result

    response = await get_intervention_suggestion_result(
        session,
        anomaly.id,
    )

    assert response is None

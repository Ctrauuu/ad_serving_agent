import pytest
from pydantic import ValidationError

from app.schemas import SuggestionGenerationOutput


def _suggestion(is_primary: bool) -> dict[str, object]:
    """构造 Schema 测试所需的最小候选建议。

    Args:
        is_primary: 是否将候选项标记为主建议。

    Returns:
        可供 Pydantic 校验的候选建议字典。
    """
    return {
        "cause_id": 1,
        "action_type": "extend_observation",
        "action_params": {"hours": 2},
        "metric_evidence": {"cpa": "300"},
        "triggered_rule": "CPA 高于动态基线",
        "expected_impact": {"effect": "补充观察样本"},
        "risk_notes": "观察期间仍可能产生额外消耗",
        "is_primary": is_primary,
    }


def test_generation_output_requires_exactly_one_primary() -> None:
    """验证建议集合必须包含且仅包含一条主建议。"""
    result = SuggestionGenerationOutput.model_validate(
        {
            "suggestions": [
                _suggestion(True),
                _suggestion(False),
            ]
        }
    )

    assert len(result.suggestions) == 2

    with pytest.raises(
        ValidationError,
        match="必须且只能包含一条主建议",
    ):
        SuggestionGenerationOutput.model_validate(
            {
                "suggestions": [
                    _suggestion(False),
                    _suggestion(False),
                ]
            }
        )

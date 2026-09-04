from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas import (
    CauseAnalysisOutput,
    CauseEvidence,
    CauseHypothesis,
)


def make_cause(confidence: str = "0.800") -> CauseHypothesis:
    """创建归因 Schema 测试数据。

    Args:
        confidence: 假设置信度。

    Returns:
        可用于测试的原因假设。
    """
    return CauseHypothesis(
        cause_type="素材疲劳",
        hypothesis="素材吸引了低意向用户",
        confidence=Decimal(confidence),
        evidence_sources=[
            CauseEvidence(
                type="metric",
                ref="metric:valid_lead_rate",
            )
        ],
    )


def test_cause_output_requires_multiple_hypotheses() -> None:
    """验证归因结果至少包含两个原因假设。"""
    with pytest.raises(ValidationError):
        CauseAnalysisOutput(causes=[make_cause()])

    result = CauseAnalysisOutput(
        causes=[make_cause(), make_cause("0.600")]
    )
    assert len(result.causes) == 2


def test_cause_confidence_must_be_between_zero_and_one() -> None:
    """验证置信度必须位于零到一之间。"""
    with pytest.raises(ValidationError):
        make_cause("1.100")


def test_cause_requires_evidence() -> None:
    """验证原因假设必须至少包含一条证据。"""
    with pytest.raises(ValidationError):
        CauseHypothesis(
            cause_type="人群过宽",
            hypothesis="定向范围过宽",
            confidence=Decimal("0.700"),
            evidence_sources=[],
        )

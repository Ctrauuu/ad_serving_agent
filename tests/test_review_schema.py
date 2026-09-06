from datetime import datetime

from app.models import CaseLibrary, ReviewReport
from app.schemas import (
    CaseLibraryRead,
    ReviewCaseCandidate,
    ReviewGenerationOutput,
    ReviewReportRead,
)


def test_review_report_read_validates_orm_record() -> None:
    """验证复盘报告 ORM 可以转换为接口响应。"""
    report = ReviewReport(
        id=3,
        campaign_id=5,
        version=2,
        overall_metrics={"cost": 42000, "lead": 180},
        strategy_evaluation={"verdict": "达标"},
        intervention_evaluation={"action_6": {"verdict": "有效"}},
        reusable_conclusion="主力渠道可复用",
        lessons="素材疲劳需要提前发现",
        improvement="缩短观察周期",
        generated_at=datetime(2026, 9, 6, 12),
    )

    result = ReviewReportRead.model_validate(report)

    assert result.version == 2
    assert result.overall_metrics == {
        "cost": 42000,
        "lead": 180,
    }
    assert result.reusable_conclusion == "主力渠道可复用"


def test_review_generation_output_validates_case() -> None:
    """验证模型复盘输出包含可沉淀的结构化案例。"""
    result = ReviewGenerationOutput.model_validate(
        {
            "reusable_conclusion": "搜索渠道适合高意图线索获取。",
            "lessons": "素材需要在 CTR 下滑前轮换。",
            "improvement": "下一轮增加素材刷新频率。",
            "cases": [
                {
                    "case_type": "intervention",
                    "scene_desc": "搜索广告 CPA 连续上升。",
                    "anomaly_type": "成本飙升",
                    "cause": "素材疲劳",
                    "action": "replace_creative",
                    "effectiveness": "有效",
                    "conclusion": "更换素材后 CPA 下降。",
                }
            ],
        }
    )

    assert isinstance(result.cases[0], ReviewCaseCandidate)
    assert result.cases[0].effectiveness == "有效"


def test_case_library_read_hides_vector_id() -> None:
    """验证案例库响应只公开业务字段而不暴露向量实现细节。"""
    case = CaseLibrary(
        id=8,
        case_type="anomaly",
        campaign_id=5,
        scene_desc="CPA 上升",
        anomaly_type="成本飙升",
        cause="素材疲劳",
        action="replace_creative",
        effectiveness="失败",
        conclusion="需提前更新素材",
        vector_id="8",
        created_at=datetime(2026, 9, 6, 12),
    )

    result = CaseLibraryRead.model_validate(case)

    assert result.case_type == "anomaly"
    assert "vector_id" not in result.model_dump()

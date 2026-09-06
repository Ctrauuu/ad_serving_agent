from sqlalchemy import UniqueConstraint

from app.models import KnowledgeDoc, ReviewReport


def test_review_report_matches_existing_table() -> None:
    """验证复盘报告模型映射字段和版本唯一约束。"""
    assert ReviewReport.__tablename__ == "review_report"
    assert set(ReviewReport.__table__.columns.keys()) == {
        "id",
        "campaign_id",
        "version",
        "overall_metrics",
        "strategy_evaluation",
        "intervention_evaluation",
        "reusable_conclusion",
        "lessons",
        "improvement",
        "generated_at",
    }
    assert any(
        isinstance(constraint, UniqueConstraint)
        and constraint.name == "uk_campaign_version"
        for constraint in ReviewReport.__table__.constraints
    )
    assert (
        ReviewReport.__table__.c.version.server_default
        is not None
    )


def test_knowledge_doc_matches_existing_table() -> None:
    """验证知识文档模型映射字段、索引和默认值。"""
    assert KnowledgeDoc.__tablename__ == "knowledge_doc"
    assert set(KnowledgeDoc.__table__.columns.keys()) == {
        "id",
        "title",
        "doc_type",
        "source_ref",
        "ragflow_doc_id",
        "chunk_count",
        "parse_status",
        "created_at",
    }
    assert {
        index.name
        for index in KnowledgeDoc.__table__.indexes
    } == {"idx_type"}
    assert (
        KnowledgeDoc.__table__.c.chunk_count.server_default
        is not None
    )
    assert (
        KnowledgeDoc.__table__.c.parse_status.server_default
        is not None
    )

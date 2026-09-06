from datetime import datetime

import pytest

from ad_platform_mock.server import (
    _groups,
    _plans,
    adjust_bid,
    adjust_budget,
    create_ad_group,
    create_ad_plan,
    get_ad_metrics,
    get_ad_status,
    mcp,
    pause_ad_group,
    replace_creative,
    resume_ad_group,
)


def test_mock_platform_tools_and_status_flow() -> None:
    _plans.clear()
    _groups.clear()

    assert {
        tool.name
        for tool in mcp._tool_manager.list_tools()
    } == {
        "create_ad_plan",
        "create_ad_group",
        "get_ad_status",
        "pause_ad_group",
        "resume_ad_group",
        "adjust_budget",
        "adjust_bid",
        "replace_creative",
        "get_ad_metrics",
    }

    plan = create_ad_plan("测试计划", 1000, 100)
    plan_id = plan["ad_platform_task_id"]
    group = create_ad_group(
        plan_id,
        "测试广告组",
        audience_id=1,
        creative_id=1,
        budget_daily=100,
        bid=5,
    )
    group_id = group["ad_platform_group_id"]

    assert get_ad_status(plan_id)["status"] == "已上线"
    group_state = get_ad_status(group_id)
    assert group_state["status"] == "已上线"
    assert group_state["budget_daily"] == 100
    assert group_state["bid"] == 5
    assert group_state["creative_id"] == 1
    assert "metric_reads" not in group_state
    assert pause_ad_group(group_id)["status"] == "已暂停"
    assert resume_ad_group(group_id)["status"] == "已上线"
    assert adjust_budget(group_id, 120)["budget_daily"] == 120
    assert adjust_bid(group_id, 6)["bid"] == 6
    replaced = replace_creative(group_id, 2)
    assert replaced["previous_creative_id"] == 1
    assert replaced["creative_id"] == 2
    assert get_ad_status(group_id)["creative_id"] == 2
    metrics = get_ad_metrics(group_id)

    assert set(metrics) == {
        "ad_platform_group_id",
        "impressions",
        "clicks",
        "spend",
        "conversions",
        "lead",
        "valid_lead",
        "order",
        "revenue",
        "roi",
        "data_time",
    }
    assert (
        0
        <= metrics["order"]
        <= metrics["valid_lead"]
        <= metrics["lead"]
        <= metrics["clicks"]
        <= metrics["impressions"]
    )
    assert datetime.fromisoformat(metrics["data_time"])

    with pytest.raises(ValueError, match="creative_id"):
        replace_creative(group_id, 0)

from random import Random
from typing import Any
from uuid import uuid4
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP


mcp = FastMCP(
    "ad-platform-mock",
    host="127.0.0.1",
    port=8001,
    streamable_http_path="/mcp",
    json_response=True,
)

# ponytail: 首版模拟平台使用进程内存；
# 需要模拟服务重启恢复时再替换为持久化存储。
_plans: dict[str, dict[str, Any]] = {}
_groups: dict[str, dict[str, Any]] = {}


def _new_id(prefix: str) -> str:
    return f"mock_{prefix}_{uuid4().hex[:12]}"


def _require_positive(
    field: str,
    value: float,
) -> None:
    if value <= 0:
        raise ValueError(f"{field} 必须大于 0")


def _find_entity(
    platform_id: str,
) -> dict[str, Any]:
    entity = (
        _plans.get(platform_id)
        or _groups.get(platform_id)
    )

    if entity is None:
        raise ValueError("平台任务不存在")

    return entity


@mcp.tool()
def create_ad_plan(
    name: str,
    budget_total: float,
    budget_daily: float,
) -> dict[str, Any]:
    """创建模拟广告计划。"""
    if not name.strip():
        raise ValueError("广告计划名称不能为空")

    _require_positive("budget_total", budget_total)
    _require_positive("budget_daily", budget_daily)

    platform_id = _new_id("plan")
    _plans[platform_id] = {
        "entity_type": "ad_plan",
        "platform_id": platform_id,
        "name": name,
        "budget_total": budget_total,
        "budget_daily": budget_daily,
        "status": "审核中",
    }

    return {
        "ad_platform_task_id": platform_id,
        "status": "审核中",
    }


@mcp.tool()
def create_ad_group(
    ad_platform_task_id: str,
    name: str,
    audience_id: int,
    creative_id: int,
    budget_daily: float,
    bid: float,
) -> dict[str, Any]:
    """在指定广告计划下创建模拟广告组。"""
    if ad_platform_task_id not in _plans:
        raise ValueError("广告计划不存在")

    if not name.strip():
        raise ValueError("广告组名称不能为空")

    if audience_id <= 0:
        raise ValueError("audience_id 必须大于 0")

    if creative_id <= 0:
        raise ValueError("creative_id 必须大于 0")

    _require_positive("budget_daily", budget_daily)
    _require_positive("bid", bid)

    platform_id = _new_id("group")
    _groups[platform_id] = {
        "entity_type": "ad_group",
        "platform_id": platform_id,
        "ad_platform_task_id": ad_platform_task_id,
        "name": name,
        "audience_id": audience_id,
        "creative_id": creative_id,
        "budget_daily": budget_daily,
        "bid": bid,
        "status": "审核中",
        "metric_reads": 0,
    }

    return {
        "ad_platform_group_id": platform_id,
        "status": "审核中",
    }


@mcp.tool()
def get_ad_status(
    platform_id: str,
) -> dict[str, Any]:
    """查询平台任务状态，首次查询后模拟审核通过。"""
    entity = _find_entity(platform_id)

    if entity["status"] == "审核中":
        entity["status"] = "已上线"

    return {
        "platform_id": platform_id,
        "entity_type": entity["entity_type"],
        "status": entity["status"],
    }


@mcp.tool()
def pause_ad_group(
    ad_platform_group_id: str,
) -> dict[str, Any]:
    """暂停已上线广告组。"""
    group = _groups.get(ad_platform_group_id)

    if group is None:
        raise ValueError("广告组不存在")

    if group["status"] != "已上线":
        raise ValueError("当前广告组状态不允许暂停")

    group["status"] = "已暂停"

    return {
        "ad_platform_group_id": ad_platform_group_id,
        "status": "已暂停",
    }


@mcp.tool()
def resume_ad_group(
    ad_platform_group_id: str,
) -> dict[str, Any]:
    """恢复已暂停广告组。"""
    group = _groups.get(ad_platform_group_id)

    if group is None:
        raise ValueError("广告组不存在")

    if group["status"] != "已暂停":
        raise ValueError("当前广告组状态不允许恢复")

    group["status"] = "已上线"

    return {
        "ad_platform_group_id": ad_platform_group_id,
        "status": "已上线",
    }


@mcp.tool()
def adjust_budget(
    platform_id: str,
    budget_daily: float,
) -> dict[str, Any]:
    """调整广告计划或广告组日预算。"""
    _require_positive("budget_daily", budget_daily)

    entity = _find_entity(platform_id)
    entity["budget_daily"] = budget_daily

    return {
        "platform_id": platform_id,
        "budget_daily": budget_daily,
        "status": entity["status"],
    }


@mcp.tool()
def adjust_bid(
    ad_platform_group_id: str,
    bid: float,
) -> dict[str, Any]:
    """调整广告组出价。"""
    _require_positive("bid", bid)

    group = _groups.get(ad_platform_group_id)

    if group is None:
        raise ValueError("广告组不存在")

    group["bid"] = bid

    return {
        "ad_platform_group_id": ad_platform_group_id,
        "bid": bid,
        "status": group["status"],
    }


@mcp.tool()
def get_ad_metrics(
    ad_platform_group_id: str,
) -> dict[str, Any]:
    """获取一个采集周期内的模拟广告指标。"""
    group = _groups.get(ad_platform_group_id)

    if group is None:
        raise ValueError("广告组不存在")

    data_time = datetime.now(
        timezone.utc
    ).isoformat()

    if group["status"] == "已暂停":
        return {
            "ad_platform_group_id": (
                ad_platform_group_id
            ),
            "impressions": 0,
            "clicks": 0,
            "spend": 0.0,
            "conversions": 0,
            "lead": 0,
            "valid_lead": 0,
            "order": 0,
            "revenue": 0.0,
            "roi": None,
            "data_time": data_time,
        }

    group["metric_reads"] += 1
    random = Random(
        f"{ad_platform_group_id}:"
        f"{group['metric_reads']}"
    )

    impressions = random.randint(1000, 5000)
    clicks = random.randint(
        50,
        min(500, impressions),
    )
    lead = random.randint(
        1,
        min(50, clicks),
    )
    valid_lead = random.randint(0, lead)
    order = random.randint(0, valid_lead)

    spend = round(
        min(
            float(group["budget_daily"]),
            clicks * random.uniform(1.0, 3.0),
        ),
        2,
    )
    revenue = round(
        order * random.uniform(500.0, 3000.0),
        2,
    )
    roi = (
        round(revenue / spend, 4)
        if spend > 0
        else None
    )

    return {
        "ad_platform_group_id": (
            ad_platform_group_id
        ),
        "impressions": impressions,
        "clicks": clicks,
        "spend": spend,
        # 保留旧字段，兼容已经存在的调用方。
        "conversions": lead,
        "lead": lead,
        "valid_lead": valid_lead,
        "order": order,
        "revenue": revenue,
        "roi": roi,
        "data_time": data_time,
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
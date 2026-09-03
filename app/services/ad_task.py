from datetime import datetime, time
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.ad_platform import (
    call_ad_platform_tool,
)
from app.models import (
    AdGroup,
    AdPlan,
    Audience,
    Campaign,
    Channel,
    Creative,
    Keyword,
    Strategy,
)
from app.schemas import (
    AdGroupTaskRead,
    AdPlanTaskRead,
    AdTaskCreateRequest,
    AdTaskCreateResult,
    KeywordRead,
    StrategyPlan,
    AdGroupStatusRead,
    AdTaskStatusResult,
)


async def list_ad_tasks(
    session: AsyncSession,
    campaign: Campaign,
) -> AdTaskCreateResult:
    plans = list(
        (
            await session.scalars(
                select(AdPlan)
                .where(
                    AdPlan.campaign_id == campaign.id
                )
                .order_by(AdPlan.id)
            )
        ).all()
    )

    plan_ids = [plan.id for plan in plans]
    groups = []

    if plan_ids:
        groups = list(
            (
                await session.scalars(
                    select(AdGroup)
                    .where(
                        AdGroup.ad_plan_id.in_(plan_ids)
                    )
                    .order_by(AdGroup.id)
                )
            ).all()
        )

    group_ids = [group.id for group in groups]
    keywords = []

    if group_ids:
        keywords = list(
            (
                await session.scalars(
                    select(Keyword)
                    .where(
                        Keyword.ad_group_id.in_(
                            group_ids
                        )
                    )
                    .order_by(Keyword.id)
                )
            ).all()
        )

    keywords_by_group: dict[int, list[Keyword]] = {}

    for keyword in keywords:
        keywords_by_group.setdefault(
            keyword.ad_group_id,
            [],
        ).append(keyword)

    groups_by_plan: dict[int, list[AdGroup]] = {}

    for group in groups:
        groups_by_plan.setdefault(
            group.ad_plan_id,
            [],
        ).append(group)

    return AdTaskCreateResult(
        campaign_id=campaign.id,
        status=campaign.status,
        plans=[
            AdPlanTaskRead(
                id=plan.id,
                campaign_id=plan.campaign_id,
                strategy_id=plan.strategy_id,
                channel_id=plan.channel_id,
                name=plan.name,
                budget_daily=plan.budget_daily,
                budget_total=plan.budget_total,
                bid_strategy=plan.bid_strategy,
                start_time=plan.start_time,
                end_time=plan.end_time,
                ad_platform_task_id=(
                    plan.ad_platform_task_id
                ),
                status=plan.status,
                error_message=plan.error_message,
                groups=[
                    AdGroupTaskRead(
                        id=group.id,
                        ad_plan_id=group.ad_plan_id,
                        campaign_id=group.campaign_id,
                        name=group.name,
                        audience_id=group.audience_id,
                        creative_id=group.creative_id,
                        bid=group.bid,
                        budget_daily=group.budget_daily,
                        ad_platform_group_id=(
                            group.ad_platform_group_id
                        ),
                        status=group.status,
                        error_message=(
                            group.error_message
                        ),
                        keywords=[
                            KeywordRead.model_validate(
                                keyword
                            )
                            for keyword
                            in keywords_by_group.get(
                                group.id,
                                [],
                            )
                        ],
                    )
                    for group
                    in groups_by_plan.get(
                        plan.id,
                        [],
                    )
                ],
            )
            for plan in plans
        ],
    )


async def _create_local_tasks(
    session: AsyncSession,
    campaign: Campaign,
    strategy: Strategy,
    strategy_plan: StrategyPlan,
    form: AdTaskCreateRequest,
) -> list[AdPlan]:
    day_count = (
        campaign.end_date - campaign.start_date
    ).days + 1

    if day_count <= 0:
        raise ValueError("活动投放周期无效")

    groups_by_channel = {
        item.channel: item.groups
        for item in strategy_plan.ad_group_structure
    }

    plans: list[AdPlan] = []

    for channel in strategy_plan.channel_mix:
        group_names = groups_by_channel.get(
            channel.channel_name
        )

        if not group_names:
            raise ValueError(
                f"渠道 {channel.channel_name} "
                "没有广告组配置"
            )

        budget_total = strategy_plan.budget_split[
            channel.channel_name
        ]
        budget_daily = (
            budget_total / Decimal(day_count)
        ).quantize(Decimal("0.01"))

        group_budget_daily = (
            budget_daily / Decimal(len(group_names))
        ).quantize(Decimal("0.01"))

        if group_budget_daily <= 0:
            raise ValueError(
                f"渠道 {channel.channel_name} "
                "广告组日预算过低"
            )

        ad_plan = AdPlan(
            campaign_id=campaign.id,
            strategy_id=strategy.id,
            channel_id=channel.channel_id,
            name=(
                f"{campaign.name}-{channel.channel_name}"
            )[:128],
            budget_daily=budget_daily,
            budget_total=budget_total,
            bid_strategy=strategy_plan.bid_strategy,
            start_time=datetime.combine(
                campaign.start_date,
                time.min,
            ),
            end_time=datetime.combine(
                campaign.end_date,
                time.max,
            ),
            status="待创建",
        )
        session.add(ad_plan)
        await session.flush()
        plans.append(ad_plan)

        channel_keywords = (
            strategy_plan.keyword_plan.get(
                channel.channel_name,
                [],
            )
        )

        for group_name in group_names:
            ad_group = AdGroup(
                ad_plan_id=ad_plan.id,
                campaign_id=campaign.id,
                name=group_name[:128],
                audience_id=form.audience_id,
                creative_id=form.creative_id,
                bid=form.bid,
                budget_daily=group_budget_daily,
                status="待创建",
            )
            session.add(ad_group)
            await session.flush()

            for word in channel_keywords:
                normalized_word = word.strip()

                if not normalized_word:
                    continue

                if len(normalized_word) > 128:
                    raise ValueError(
                        "关键词长度不能超过128个字符"
                    )

                session.add(
                    Keyword(
                        ad_group_id=ad_group.id,
                        word=normalized_word,
                        match_type="短语匹配",
                        bid=form.bid,
                    )
                )

    campaign.status = "任务创建中"
    await session.commit()

    return plans


async def create_ad_tasks(
    session: AsyncSession,
    campaign: Campaign,
    form: AdTaskCreateRequest,
) -> AdTaskCreateResult:
    # create_ad_tasks()
    #     │
    #     ├── 校验 Campaign / Strategy / Audience / Creative / Channel
    #     │
    #     ├── 如果本地任务不存在
    #     │      ↓
    #     │   _create_local_tasks()
    #     │      ↓
    #     │   创建 AdPlan / AdGroup / Keyword 到 MySQL
    #     │
    #     ├── 调 MCP 创建真正的平台 AdPlan
    #     │
    #     ├── 调 MCP 创建真正的平台 AdGroup
    #     │
    #     ├── 查询平台状态并回写数据库
    #     │
    #     ├── 判断是否全部上线
    #     │
    #     └── _load_result()
    #            ↓
    #         把最终任务树查出来返回
    if campaign.status not in {
        "策略已确认",
        "任务创建中",
        "投放中",
    }:
        raise ValueError(
            "活动尚未确认投放策略"
        )

    strategy = await session.scalar(
        select(Strategy)
        .where(
            Strategy.campaign_id == campaign.id,
            Strategy.status == "已确认",
        )
        .order_by(
            Strategy.version.desc(),
            Strategy.id.desc(),
        )
        .limit(1)
    )

    if strategy is None:
        raise ValueError("活动不存在已确认策略")

    try:
        strategy_plan = StrategyPlan(
            channel_mix=strategy.channel_mix, # type: ignore
            budget_split=strategy.budget_split,
            ad_group_structure=(
                strategy.ad_group_structure
            ), # type: ignore
            audience_plan=(
                strategy.audience_plan or {}
            ),
            keyword_plan=(
                strategy.keyword_plan or {}
            ),
            creative_test_plan=(
                strategy.creative_test_plan or {}
            ),
            bid_strategy=(
                strategy.bid_strategy or ""
            ),
            expected_metrics=(
                strategy.expected_metrics or {}
            ),
            risk_notes=strategy.risk_notes or "",
        )
    except ValidationError as exc:
        raise ValueError(
            "已确认策略结构无效"
        ) from exc

    audience = await session.get(
        Audience,
        form.audience_id,
    )
    if audience is None or audience.status != "启用":
        raise ValueError("人群不存在或未启用")

    creative = await session.get(
        Creative,
        form.creative_id,
    )
    if (
        creative is None
        or creative.status != "已审核"
    ):
        raise ValueError("素材不存在或未审核")

    channel_ids = {
        item.channel_id
        for item in strategy_plan.channel_mix
    }
    channels = list(
        (
            await session.scalars(
                select(Channel).where(
                    Channel.id.in_(channel_ids)
                )
            )
        ).all()
    )
    channels_by_id = {
        channel.id: channel
        for channel in channels
    }

    for selected in strategy_plan.channel_mix:
        channel = channels_by_id.get(
            selected.channel_id
        )

        if (
            channel is None
            or channel.status != "启用"
            or channel.name != selected.channel_name
        ):
            raise ValueError(
                f"渠道不可用："
                f"{selected.channel_name}"
            )

    plans = list(
        (
            await session.scalars(
                select(AdPlan)
                .where(
                    AdPlan.campaign_id == campaign.id,
                    AdPlan.strategy_id == strategy.id,
                )
                .order_by(AdPlan.id)
            )
        ).all()
    )

    if not plans:
        plans = await _create_local_tasks(
            session=session,
            campaign=campaign,
            strategy=strategy,
            strategy_plan=strategy_plan,
            form=form,
        )

    plan_ids = [plan.id for plan in plans]
    groups = list(
        (
            await session.scalars(
                select(AdGroup)
                .where(
                    AdGroup.ad_plan_id.in_(plan_ids)
                )
                .order_by(AdGroup.id)
            )
        ).all()
    )

    if any(
        group.audience_id != form.audience_id
        or group.creative_id != form.creative_id
        or group.bid != form.bid
        for group in groups
    ):
        raise ValueError(
            "广告任务已按其他参数拆解，"
            "请使用原参数重试"
        )

    groups_by_plan: dict[int, list[AdGroup]] = {}

    for group in groups:
        groups_by_plan.setdefault(
            group.ad_plan_id,
            [],
        ).append(group)

    for plan in plans:
        plan_groups = groups_by_plan.get(
            plan.id,
            [],
        )

        if plan.status != "已上线":
            try:
                if not plan.ad_platform_task_id:
                    result = await call_ad_platform_tool(
                        "create_ad_plan",
                        {
                            "name": plan.name,
                            "budget_total": float(
                                plan.budget_total
                            ),
                            "budget_daily": float(
                                plan.budget_daily
                            ),
                        },
                    )
                    plan.ad_platform_task_id = str(
                        result["ad_platform_task_id"]
                    )
                    plan.status = str(
                        result["status"]
                    )
                    plan.error_message = None

                    # 平台ID必须立即保存，避免状态查询
                    # 失败后重复创建平台计划。
                    await session.commit()

                status_result = (
                    await call_ad_platform_tool(
                        "get_ad_status",
                        {
                            "platform_id": (
                                plan.ad_platform_task_id
                            )
                        },
                    )
                )
                plan.status = str(
                    status_result["status"]
                )
                plan.error_message = None
                await session.commit()

            except Exception as exc:
                plan.status = "创建失败"
                plan.error_message = str(exc)[:512]

                for group in plan_groups:
                    if group.status != "已上线":
                        group.status = "创建失败"
                        group.error_message = (
                            "所属广告计划未上线"
                        )

                await session.commit()
                continue

        for group in plan_groups:
            if group.status == "已上线":
                continue

            try:
                if not group.ad_platform_group_id:
                    result = await call_ad_platform_tool(
                        "create_ad_group",
                        {
                            "ad_platform_task_id": (
                                plan.ad_platform_task_id
                            ),
                            "name": group.name,
                            "audience_id": (
                                group.audience_id
                            ),
                            "creative_id": (
                                group.creative_id
                            ),
                            "budget_daily": float(
                                group.budget_daily
                            ),
                            "bid": float(group.bid),
                        },
                    )
                    group.ad_platform_group_id = str(
                        result[
                            "ad_platform_group_id"
                        ]
                    )
                    group.status = str(
                        result["status"]
                    )
                    group.error_message = None
                    await session.commit()

                status_result = (
                    await call_ad_platform_tool(
                        "get_ad_status",
                        {
                            "platform_id": (
                                group.ad_platform_group_id
                            )
                        },
                    )
                )
                group.status = str(
                    status_result["status"]
                )
                group.error_message = None
                await session.commit()

            except Exception as exc:
                group.status = "创建失败"
                group.error_message = str(exc)[:512]
                await session.commit()

    all_online = (
        bool(plans)
        and bool(groups)
        and all(
            plan.status == "已上线"
            for plan in plans
        )
        and all(
            group.status == "已上线"
            for group in groups
        )
    )

    campaign.status = (
        "投放中"
        if all_online
        else "任务创建中"
    )
    await session.commit()

    return await list_ad_tasks(
        session,
        campaign,
    )


async def sync_ad_task_status(
    session: AsyncSession,
    campaign: Campaign,
    plan: AdPlan,
) -> AdTaskStatusResult:
    # 传入一个 AdPlan
    #    ↓
    # 查它下面所有 AdGroup
    #    ↓
    # 调用 MCP 查询 AdPlan 平台状态
    #    ↓
    # 调用 MCP 查询每个 AdGroup 平台状态
    #    ↓
    # 更新本地 status
    #    ↓
    # 再检查整个 Campaign 的所有 Plan / Group
    #    ↓
    # 如果全部已上线
    #    ↓
    # Campaign = 投放中
    #    ↓
    # 返回这个 Plan + Groups 的最新状态
    groups = list(
        (
            await session.scalars(
                select(AdGroup)
                .where(
                    AdGroup.ad_plan_id == plan.id
                )
                .order_by(AdGroup.id)
            )
        ).all()
    )

    if plan.ad_platform_task_id:
        try:
            result = await call_ad_platform_tool(
                "get_ad_status",
                {
                    "platform_id": (
                        plan.ad_platform_task_id
                    )
                },
            )
            plan.status = str(result["status"])
            plan.error_message = None
        except Exception as exc:
            # 状态同步失败不代表平台任务创建失败，
            # 保留最后一次已知状态。
            plan.error_message = str(exc)[:512]

    for group in groups:
        if not group.ad_platform_group_id:
            continue

        try:
            result = await call_ad_platform_tool(
                "get_ad_status",
                {
                    "platform_id": (
                        group.ad_platform_group_id
                    )
                },
            )
            group.status = str(result["status"])
            group.error_message = None
        except Exception as exc:
            group.error_message = str(exc)[:512]

    all_plans = list(
        (
            await session.scalars(
                select(AdPlan).where(
                    AdPlan.campaign_id == campaign.id
                )
            )
        ).all()
    )
    all_plan_ids = [
        item.id
        for item in all_plans
    ]

    all_groups = []

    if all_plan_ids:
        all_groups = list(
            (
                await session.scalars(
                    select(AdGroup).where(
                        AdGroup.ad_plan_id.in_(
                            all_plan_ids
                        )
                    )
                )
            ).all()
        )

    if (
        all_plans
        and all_groups
        and all(
            item.status == "已上线"
            for item in all_plans
        )
        and all(
            item.status == "已上线"
            for item in all_groups
        )
    ):
        campaign.status = "投放中"

    await session.commit()

    return AdTaskStatusResult(
        id=plan.id,
        campaign_id=plan.campaign_id,
        ad_platform_task_id=(
            plan.ad_platform_task_id
        ),
        status=plan.status,
        error_message=plan.error_message,
        groups=[
            AdGroupStatusRead(
                id=group.id,
                ad_platform_group_id=(
                    group.ad_platform_group_id
                ),
                status=group.status,
                error_message=group.error_message,
            )
            for group in groups
        ],
    )

async def list_ad_groups(
    session: AsyncSession,
    campaign: Campaign,
) -> list[AdGroupTaskRead]:
    task_result = await list_ad_tasks(
        session,
        campaign,
    )

    return [
        group
        for plan in task_result.plans
        for group in plan.groups
    ]
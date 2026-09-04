import json
from datetime import datetime
from decimal import Decimal

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.milvus import milvus_client
from app.models import (
    Campaign,
    Channel,
    Product,
    Strategy,
    StrategyEvidence,
)
from app.schemas import (
    StrategyDetail,
    StrategyEvidenceRead,
    StrategyPlan,
    StrategyRead,
    StructuredGoal,
    StrategyConfirmResult,
    
)
from app.services.embedding import embed_goal
from app.services.goal import get_goal_llm


_strategy_parser = PydanticOutputParser(
    pydantic_object=StrategyPlan,
)

_STRATEGY_SYSTEM_PROMPT = f"""
你负责根据投放目标和可信依据生成可执行的广告投放策略。

规则：
1. 只能使用候选渠道中的 channel_id 和 channel_name。
2. budget_split 必须覆盖 channel_mix 中的全部渠道。
3. 各渠道预算必须大于 0，预算总和不能超过活动预算。
4. 历史策略仅作为参考，不能照搬与当前目标冲突的内容。
5. 历史策略为空时，基于渠道规则和产品卖点生成。
6. expected_metrics 必须是可量化的数值指标。
7. 必须输出合法 JSON。

{_strategy_parser.get_format_instructions()}
"""


def _to_json(value: object) -> str:
    """序列化提示词数据。

    Args:
        value: 待处理的输入值。

    Returns:
        返回类型为 str 的执行结果。
    """
    return json.dumps(
        value,
        ensure_ascii=False,
        default=str,
    )


async def _generate_plan(
    goal: dict,
    budget_limit: Decimal,
    product: dict,
    channels: list[dict],
    history: list[dict],
) -> StrategyPlan:
    """调用模型生成结构化策略。

    Args:
        goal: 结构化投放目标。
        budget_limit: 活动预算上限。
        product: 产品信息。
        channels: 候选渠道。
        history: 历史策略。

    Returns:
        返回类型为 StrategyPlan 的执行结果。
    """
    user_content = f"""
活动目标：
{_to_json(goal)}

活动预算上限：
{budget_limit}

产品信息：
{_to_json(product)}

候选渠道：
{_to_json(channels)}

相似历史策略：
{_to_json(history)}
"""

    response = await get_goal_llm().ainvoke(
        [
            SystemMessage(
                content=_STRATEGY_SYSTEM_PROMPT
            ),
            HumanMessage(content=user_content),
        ]
    )

    if not isinstance(response.content, str):
        raise ValueError("模型未返回文本内容")

    try:
        return _strategy_parser.parse(
            response.content
        )
    except OutputParserException as exc:
        raise ValueError(
            "模型返回内容不符合策略结构"
        ) from exc


def _validate_strategy_plan(
    plan: StrategyPlan,
    budget_limit: Decimal,
    channels_by_id: dict[int, Channel],
) -> None:
    """校验生成策略。

    Args:
        plan: 广告计划对象。
        budget_limit: 活动预算上限。
        channels_by_id: 函数输入参数。

    Returns:
        无返回值。
    """
    total_budget = sum(
        plan.budget_split.values(),
        Decimal("0"),
    )

    if total_budget > budget_limit:
        raise ValueError(
            f"渠道预算总和 {total_budget} "
            f"超过活动预算 {budget_limit}"
        )

    for selected in plan.channel_mix:
        channel = channels_by_id.get(
            selected.channel_id
        )

        if (
            channel is None
            or channel.name != selected.channel_name
        ):
            raise ValueError(
                f"模型选择了不可用渠道："
                f"{selected.channel_name}"
            )


async def generate_strategy(
    session: AsyncSession,
    campaign: Campaign,
) -> StrategyDetail:
    """召回依据并生成策略。

    Args:
        session: 数据库异步会话。
        campaign: 活动 ORM 对象。

    Returns:
        返回类型为 StrategyDetail 的执行结果。
    """
    if campaign.status not in {
        "目标已结构化",
        "策略生成中",
    }:
        raise ValueError(
            "当前活动状态不允许生成策略"
        )

    if campaign.structured_goal is None:
        raise ValueError(
            "活动尚未完成目标结构化"
        )

    try:
        goal = StructuredGoal.model_validate(
            campaign.structured_goal
        )
    except ValidationError as exc:
        raise ValueError(
            "活动 structured_goal 格式无效"
        ) from exc

    product = await session.get(
        Product,
        campaign.product_id,
    )
    if product is None:
        raise ValueError(
            "活动关联产品不存在"
        )

    channels = list(
        (
            await session.scalars(
                select(Channel)
                .where(Channel.status == "启用")
                .order_by(Channel.id)
            )
        ).all()
    )
    if not channels:
        raise ValueError(
            "当前没有可用投放渠道"
        )

    query_vector = await embed_goal(
        goal,
        text_type="query",
    )

    matches = (
        await milvus_client.search_similar_strategies(
            goal_vector=query_vector,
            current_campaign_id=campaign.id,
            limit=5,
        )
    )

    historical_by_id: dict[int, Strategy] = {}

    if matches:
        strategy_ids = [
            int(match["strategy_id"])
            for match in matches
        ]

        historical_strategies = list(
            (
                await session.scalars(
                    select(Strategy).where(
                        Strategy.id.in_(strategy_ids),
                        Strategy.status == "已确认",
                    )
                )
            ).all()
        )

        historical_by_id = {
            strategy.id: strategy
            for strategy in historical_strategies
        }

    usable_matches = [
        match
        for match in matches
        if int(match["strategy_id"])
        in historical_by_id
    ]

    history_context: list[dict] = []

    for match in usable_matches:
        historical = historical_by_id[
            int(match["strategy_id"])
        ]

        history_context.append(
            {
                "strategy_id": historical.id,
                "campaign_id": (
                    historical.campaign_id
                ),
                "similarity": match["score"],
                "channel_mix": (
                    historical.channel_mix
                ),
                "budget_split": (
                    historical.budget_split
                ),
                "audience_plan": (
                    historical.audience_plan
                ),
                "creative_test_plan": (
                    historical.creative_test_plan
                ),
                "bid_strategy": (
                    historical.bid_strategy
                ),
                "expected_metrics": (
                    historical.expected_metrics
                ),
                "risk_notes": (
                    historical.risk_notes
                ),
            }
        )

    product_context = {
        "id": product.id,
        "name": product.name,
        "category": product.category,
        "selling_points": product.selling_points,
        "target_audience": (
            product.target_audience_desc
        ),
    }

    channel_context = [
        {
            "id": channel.id,
            "name": channel.name,
            "platform": channel.platform,
            "min_budget_daily": (
                channel.min_budget_daily
            ),
            "rules": channel.rules,
        }
        for channel in channels
    ]

    plan = await _generate_plan(
        goal=goal.model_dump(mode="json"),
        budget_limit=campaign.budget_total,
        product=product_context,
        channels=channel_context,
        history=history_context,
    )

    channels_by_id = {
        channel.id: channel
        for channel in channels
    }

    _validate_strategy_plan(
        plan=plan,
        budget_limit=campaign.budget_total,
        channels_by_id=channels_by_id,
    )

    # ponytail: 当前低并发阶段使用 max+1；
    # 需要并发生成时增加唯一索引和冲突重试。
    latest_version = await session.scalar(
        select(func.max(Strategy.version)).where(
            Strategy.campaign_id
            == campaign.id
        )
    ) or 0

    strategy = Strategy(
        campaign_id=campaign.id,
        version=latest_version + 1,
        channel_mix=[
            item.model_dump(mode="json")
            for item in plan.channel_mix
        ],
        budget_split={
            name: float(amount)
            for name, amount
            in plan.budget_split.items()
        },
        ad_group_structure=[
            item.model_dump(mode="json")
            for item
            in plan.ad_group_structure
        ],
        audience_plan=plan.audience_plan,
        keyword_plan=plan.keyword_plan,
        creative_test_plan=(
            plan.creative_test_plan
        ),
        bid_strategy=plan.bid_strategy,
        expected_metrics={
            name: float(value)
            for name, value
            in plan.expected_metrics.items()
        },
        risk_notes=plan.risk_notes,
        status="待确认",
    )

    session.add(strategy)
    await session.flush()

    evidence: list[StrategyEvidence] = []

    if usable_matches:
        for match in usable_matches:
            historical = historical_by_id[
                int(match["strategy_id"])
            ]
            score = Decimal(
                str(match["score"])
            ).quantize(
                Decimal("0.0001")
            )

            evidence.append(
                StrategyEvidence(
                    strategy_id=strategy.id,
                    evidence_type="历史活动",
                    target_item="整体策略",
                    explanation=(
                        f"参考历史活动#"
                        f"{historical.campaign_id}"
                        f"的已确认策略，"
                        f"相似度为{score}"
                    ),
                    source_ref=(
                        f"strategy:{historical.id}"
                    ),
                    vector_score=score,
                )
            )
    else:
        evidence.append(
            StrategyEvidence(
                strategy_id=strategy.id,
                evidence_type="历史活动",
                target_item="整体策略",
                explanation=(
                    "无相似历史活动，"
                    "策略基于渠道规则和"
                    "产品卖点生成"
                ),
                source_ref=None,
                vector_score=None,
            )
        )

    for selected in plan.channel_mix:
        channel = channels_by_id[
            selected.channel_id
        ]

        explanation = channel.rules

        if not explanation:
            explanation = (
                f"{channel.platform}渠道"
                f"最低日预算为"
                f"{channel.min_budget_daily}"
            )

        evidence.append(
            StrategyEvidence(
                strategy_id=strategy.id,
                evidence_type="渠道规则",
                target_item=(
                    selected.channel_name
                ),
                explanation=explanation,
                source_ref=(
                    f"channel:{channel.id}"
                ),
                vector_score=None,
            )
        )

    product_explanation = product.selling_points

    if not product_explanation:
        product_explanation = (
            f"产品类别："
            f"{product.category or '未分类'}"
        )

    evidence.append(
        StrategyEvidence(
            strategy_id=strategy.id,
            evidence_type="产品卖点",
            target_item="整体策略",
            explanation=product_explanation,
            source_ref=f"product:{product.id}",
            vector_score=None,
        )
    )

    session.add_all(evidence)
    campaign.status = "策略生成中"

    await session.commit()
    await session.refresh(strategy)

    saved_evidence = list(
        (
            await session.scalars(
                select(StrategyEvidence)
                .where(
                    StrategyEvidence.strategy_id
                    == strategy.id
                )
                .order_by(StrategyEvidence.id)
            )
        ).all()
    )

    return StrategyDetail(
        strategy=StrategyRead.model_validate(
            strategy
        ),
        evidence=[
            StrategyEvidenceRead.model_validate(
                item
            )
            for item in saved_evidence
        ],
    )


async def get_latest_strategy(
    session: AsyncSession,
    campaign_id: int,
) -> StrategyDetail | None:
    """查询最新策略及依据。

    Args:
        session: 数据库异步会话。
        campaign_id: 活动编号。

    Returns:
        返回类型为 StrategyDetail | None 的执行结果。
    """
    strategy = await session.scalar(
        select(Strategy)
        .where(
            Strategy.campaign_id == campaign_id
        )
        .order_by(
            Strategy.version.desc(),
            Strategy.id.desc(),
        )
        .limit(1)
    )

    if strategy is None:
        return None

    evidence = list(
        (
            await session.scalars(
                select(StrategyEvidence)
                .where(
                    StrategyEvidence.strategy_id
                    == strategy.id
                )
                .order_by(StrategyEvidence.id)
            )
        ).all()
    )

    return StrategyDetail(
        strategy=StrategyRead.model_validate(
            strategy
        ),
        evidence=[
            StrategyEvidenceRead.model_validate(
                item
            )
            for item in evidence
        ],
    )

async def confirm_strategy(
    session: AsyncSession,
    campaign: Campaign,
    confirmed_by: int,
) -> StrategyConfirmResult:
    """确认策略并推进活动状态。

    Args:
        session: 数据库异步会话。
        campaign: 活动 ORM 对象。
        confirmed_by: 确认人编号。

    Returns:
        返回类型为 StrategyConfirmResult 的执行结果。
    """
    if campaign.status != "策略生成中":
        raise ValueError(
            "当前活动状态不允许确认策略"
        )

    if campaign.structured_goal is None:
        raise ValueError(
            "活动尚未完成目标结构化"
        )

    try:
        goal = StructuredGoal.model_validate(
            campaign.structured_goal
        )
    except ValidationError as exc:
        raise ValueError(
            "活动 structured_goal 格式无效"
        ) from exc

    strategy = await session.scalar(
        select(Strategy)
        .where(
            Strategy.campaign_id == campaign.id
        )
        .order_by(
            Strategy.version.desc(),
            Strategy.id.desc(),
        )
        .limit(1)
    )

    if strategy is None:
        raise ValueError(
            "活动尚未生成策略"
        )

    if strategy.status != "待确认":
        raise ValueError(
            "当前策略状态不允许确认"
        )

    document_vector = await embed_goal(
        goal,
        text_type="document",
    )

    await milvus_client.upsert_strategy_vector(
        strategy_id=strategy.id,
        campaign_id=campaign.id,
        goal_vector=document_vector,
    )

    strategy.status = "已确认"
    strategy.confirmed_by = confirmed_by
    strategy.confirmed_at = datetime.now()
    campaign.status = "策略已确认"

    await session.commit()

    return StrategyConfirmResult(
        campaign_id=campaign.id,
        strategy_id=strategy.id,
        status="策略已确认",
    )

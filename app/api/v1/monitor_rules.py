from fastapi import APIRouter

from app.api.dependencies.auth import CurrentUser, SessionDep
from app.api.routing import UnifiedResponseRoute
from app.schemas.anomaly import MonitorRuleRead
from app.services.anomaly import list_monitor_rules


router = APIRouter(
    prefix="/monitor-rules",
    tags=["monitor-rules"],
    route_class=UnifiedResponseRoute,
)


@router.get(
    "",
    response_model=None,
)
async def monitor_rule_list(
    session: SessionDep,
    _: CurrentUser,
) -> list[MonitorRuleRead]:
    """查询监控规则。

    Args:
        session: 数据库异步会话。
        _: 未使用的框架注入参数。

    Returns:
        返回类型为 list[MonitorRuleRead] 的执行结果。
    """
    rules = await list_monitor_rules(session)

    return [
        MonitorRuleRead.model_validate(rule)
        for rule in rules
    ]

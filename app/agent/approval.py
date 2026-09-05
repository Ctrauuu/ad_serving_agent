from typing import Any, Literal, TypedDict, cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class ApprovalWorkflowState(TypedDict):
    """人工审批工作流状态。"""

    approval_id: int
    suggestion_id: int
    campaign_id: int
    action_type: str
    action_params: dict[str, Any]
    risk_level: str
    decision: Literal[
        "pending",
        "approved",
        "rejected",
    ]
    approver_id: int | None
    opinion: str | None
    reason: str | None


def risk_approval_node(
    state: ApprovalWorkflowState,
) -> dict[str, object]:
    """暂停工作流并等待投放负责人的审批决定。

    Args:
        state: 当前审批、建议和动作信息。

    Returns:
        人工恢复后产生的审批决定、审批人和意见。

    Raises:
        ValueError: 恢复工作流时提供了无效决定。
    """
    decision_payload = interrupt(
        {
            "approval_id": state["approval_id"],
            "suggestion_id": state["suggestion_id"],
            "risk_level": state["risk_level"],
            "action_request": {
                "action": state["action_type"],
                "args": state["action_params"],
            },
            "description": (
                f"建议执行 {state['action_type']}，"
                f"风险等级为 {state['risk_level']}"
            ),
        }
    )

    if (
        not isinstance(decision_payload, dict)
        or not isinstance(
            decision_payload.get("approved"),
            bool,
        )
    ):
        raise ValueError("审批恢复参数无效")

    approved = decision_payload["approved"]

    return {
        "decision": (
            "approved"
            if approved
            else "rejected"
        ),
        "approver_id": decision_payload.get(
            "approver_id"
        ),
        "opinion": decision_payload.get(
            "opinion"
        ),
        "reason": decision_payload.get(
            "reason"
        ),
    }


_builder = StateGraph(ApprovalWorkflowState)
_builder.add_node(
    "risk_approval",
    risk_approval_node,
)
_builder.add_edge(START, "risk_approval")
_builder.add_edge("risk_approval", END)

approval_graph = _builder.compile(
    checkpointer=InMemorySaver()
)


def build_approval_thread_id(
    campaign_id: int,
    approval_id: int,
) -> str:
    """生成审批工作流的稳定线程编号。

    Args:
        campaign_id: 活动编号。
        approval_id: 审批记录编号。

    Returns:
        LangGraph 保存和恢复状态使用的 thread_id。
    """
    return (
        f"campaign:{campaign_id}:"
        f"approval:{approval_id}"
    )


async def start_approval_workflow(
    state: ApprovalWorkflowState,
) -> dict[str, Any]:
    """启动审批工作流并运行到人工中断节点。

    Args:
        state: 审批、建议和待执行动作的初始状态。

    Returns:
        interrupt 暴露给审批页面的 JSON 数据。

    Raises:
        RuntimeError: 工作流没有在预期节点暂停，
            或中断数据不是字典。
    """
    config: RunnableConfig = {
        "configurable": {
            "thread_id": build_approval_thread_id(
                state["campaign_id"],
                state["approval_id"],
            )
        }
    }

    result = await approval_graph.ainvoke(
        state,
        config=config,
    )

    interrupts = result.get(
        "__interrupt__",
        (),
    )

    if not interrupts:
        raise RuntimeError(
            "审批工作流未进入等待状态"
        )

    payload = interrupts[0].value

    if not isinstance(payload, dict):
        raise RuntimeError(
            "审批工作流中断数据无效"
        )

    return payload


async def resume_approval_workflow(
    campaign_id: int,
    approval_id: int,
    approved: bool,
    approver_id: int,
    opinion: str | None = None,
    reason: str | None = None,
) -> ApprovalWorkflowState:
    """使用负责人的决定恢复审批工作流。

    Args:
        campaign_id: 活动编号。
        approval_id: 审批记录编号。
        approved: 是否通过审批。
        approver_id: 投放负责人编号。
        opinion: 审批通过意见。
        reason: 审批驳回原因。

    Returns:
        执行完成后的审批工作流状态。

    Raises:
        RuntimeError: 工作流恢复后仍处于中断状态。
    """
    config: RunnableConfig = {
        "configurable": {
            "thread_id": build_approval_thread_id(
                campaign_id,
                approval_id,
            )
        }
    }

    result = await approval_graph.ainvoke(
        Command(
            resume={
                "approved": approved,
                "approver_id": approver_id,
                "opinion": opinion,
                "reason": reason,
            }
        ),
        config=config,
    )

    if result.get("__interrupt__"):
        raise RuntimeError(
            "审批工作流恢复后仍处于等待状态"
        )

    return cast(ApprovalWorkflowState, result)

from uuid import uuid4

import pytest
from langgraph.types import Command

from app.agent.approval import (
    ApprovalWorkflowState,
    approval_graph,
    build_approval_thread_id,
    resume_approval_workflow,
    start_approval_workflow,
)


def make_graph_state() -> ApprovalWorkflowState:
    """构造人工审批图的初始状态。

    Returns:
        包含审批、建议和待执行动作的初始状态。
    """
    return {
        "approval_id": 10,
        "suggestion_id": 4,
        "campaign_id": 8,
        "action_type": "pause",
        "action_params": {"ad_group_id": 32},
        "risk_level": "高",
        "decision": "pending",
        "approver_id": None,
        "opinion": None,
        "reason": None,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("approved", "expected"),
    [(True, "approved"), (False, "rejected")],
)
async def test_approval_graph_interrupts_and_resumes(
    approved: bool,
    expected: str,
) -> None:
    """验证审批图暂停后可用相同线程恢复为人工决定。"""
    config = {
        "configurable": {
            "thread_id": f"approval-test-{uuid4()}"
        }
    }

    paused = await approval_graph.ainvoke(
        make_graph_state(),
        config=config,
    )

    interrupt_value = paused["__interrupt__"][0].value
    assert interrupt_value["approval_id"] == 10
    assert interrupt_value["action_request"]["action"] == "pause"

    resumed = await approval_graph.ainvoke(
        Command(
            resume={
                "approved": approved,
                "approver_id": 3,
                "opinion": "人工决定",
            }
        ),
        config=config,
    )

    assert resumed["decision"] == expected
    assert resumed["approver_id"] == 3


@pytest.mark.asyncio
async def test_approval_graph_rejects_invalid_resume_value() -> None:
    """验证恢复参数必须包含明确的布尔审批决定。"""
    config = {
        "configurable": {
            "thread_id": f"approval-test-{uuid4()}"
        }
    }
    await approval_graph.ainvoke(
        make_graph_state(),
        config=config,
    )

    with pytest.raises(ValueError, match="审批恢复参数无效"):
        await approval_graph.ainvoke(
            Command(resume={"approved": "yes"}),
            config=config,
        )


@pytest.mark.asyncio
async def test_approval_workflow_helpers_share_thread_id() -> None:
    """验证启动和恢复函数使用相同的稳定审批线程。"""
    state = make_graph_state()
    state["approval_id"] = (
        uuid4().int % 9_000_000_000
    ) + 1

    payload = await start_approval_workflow(state)
    resumed = await resume_approval_workflow(
        campaign_id=state["campaign_id"],
        approval_id=state["approval_id"],
        approved=True,
        approver_id=3,
        opinion="同意执行",
    )

    assert payload["approval_id"] == state["approval_id"]
    assert resumed["decision"] == "approved"
    assert resumed["opinion"] == "同意执行"
    assert build_approval_thread_id(
        state["campaign_id"],
        state["approval_id"],
    ) == (
        f"campaign:{state['campaign_id']}:"
        f"approval:{state['approval_id']}"
    )

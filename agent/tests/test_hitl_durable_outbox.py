"""Tests for HITL durable outbox, crash-recovery resumption, and idempotency key."""

import pytest
from unittest.mock import AsyncMock, patch

from hitl import HITLStore, hitl_store
from models import ApprovalDecisionRequest
import state
from routers.hitl import approve_action


@pytest.mark.asyncio
async def test_hitl_record_contains_durable_idempotency_key():
    """Every created HITL request must have a deterministic or unique idempotency_key."""
    store = HITLStore(ttl_seconds=300)
    rec = await store.create(
        query="Send confidential invoice to vendor",
        session_id="sess-1",
        user_id="user-1",
        agent_plan="Action plan",
    )
    assert "idempotency_key" in rec
    assert rec["idempotency_key"].startswith("hitl-action-")
    assert rec["status"] == "pending"


@pytest.mark.asyncio
async def test_hitl_crash_recovery_resumption_after_post_claim_failure():
    """Simulate crash between decide() and complete():

    When process crashes with status 'approved', a subsequent approval/worker call
    must RESUME execution instead of returning 404.
    """
    store = HITLStore(ttl_seconds=300)
    rec = await store.create(
        query="Execute wire transfer",
        session_id="sess-crash",
        user_id="user-1",
    )
    req_id = rec["request_id"]

    # 1. First step: Human approver approves -> marked 'approved'
    decided = await store.decide(req_id, "approved", "admin_checker", "Approved payment")
    assert decided is not None
    assert decided["status"] == "approved"

    # Simulated crash: state._workflow was never completed or crashed midway.
    # Record in store is currently "approved" (NOT "executed").
    current = await store.get(req_id)
    assert current["status"] == "approved"

    # 2. Resumption step: Server restarts / worker retries.
    # decide() on already 'approved' record by the same approver should be accepted
    resumed = await store.decide(req_id, "approved", "admin_checker", "Retry after restart")
    assert resumed is not None
    assert resumed["status"] == "approved"

    # 3. Router level: approve_action handles the 'approved' in-flight record smoothly
    mock_workflow = AsyncMock()
    mock_workflow.ainvoke.return_value = {"action_result": "Payment successfully transferred $5000"}

    with patch.object(state, "_workflow", mock_workflow), patch("routers.hitl.hitl_store", store):
        req = ApprovalDecisionRequest(approver="admin_checker", note="Resume")
        result = await approve_action(req_id, req)

        assert result["status"] == "ok"
        assert result["decision"] == "approved"
        assert result["workflow_result"] == {"action_result": "Payment successfully transferred $5000"}

    # 4. Verified executed in store
    final_rec = await store.get(req_id)
    assert final_rec["status"] == "executed"
    assert final_rec["executed_at"] is not None

    # 5. Subsequent duplicate call returns idempotent "already_executed"
    with patch("routers.hitl.hitl_store", store):
        dup_result = await approve_action(req_id, req)
        assert dup_result["status"] == "already_executed"

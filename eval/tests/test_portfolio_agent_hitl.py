"""Offline demo tests use a temporary SQLite database and never call tools."""

import sqlite3
import subprocess
import sys
import json
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from portfolio_demo.agent_hitl import audit_rows, invoke


def _state(trace_id: str, action: bool = True):
    state = {"query": "Review policy", "owner_id": "maker", "trace_id": trace_id}
    if action:
        state["action_key"] = f"{trace_id}-action"
    return state


def _count(db_path):
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM executed_actions").fetchone()[0]


def test_read_specialists_cite_and_do_not_act(tmp_path):
    db = tmp_path / "demo.sqlite"
    result = invoke(db, "read", state=_state("t-read", action=False))
    assert result["status"] == "answered"
    assert "[S1]" in result["answer"]
    assert not result["__paused__"]
    assert _count(db) == 0


def test_pause_restart_approve_and_repeated_resume_does_not_execute_twice(tmp_path):
    db = tmp_path / "demo.sqlite"
    paused = invoke(db, "approve-thread", state=_state("t-approve"))
    assert paused["__paused__"]
    assert _count(db) == 0
    # invoke opens a new checkpointer connection: this is a process restart
    # equivalent for persisted graph state and the SQLite action ledger.
    approved = invoke(db, "approve-thread", decision={"approved": True, "approver": "checker"})
    assert approved["status"] == "executed"
    assert _count(db) == 1
    # A duplicate business action with the same key is safe even from a new
    # graph thread, which is stricter than simply resuming one finished thread.
    invoke(db, "retry-thread", state=_state("t-approve"))
    again = invoke(db, "retry-thread", decision={"approved": True, "approver": "checker"})
    assert again["status"] == "already_executed"
    assert _count(db) == 1
    assert {row["event"] for row in audit_rows(db, "t-approve")} >= {
        "routed", "approved", "executed", "deduplicated"
    }


def test_rejection_and_self_approval_never_execute(tmp_path):
    db = tmp_path / "demo.sqlite"
    invoke(db, "reject-thread", state=_state("t-reject"))
    rejected = invoke(db, "reject-thread", decision={"approved": False, "approver": "checker"})
    assert rejected["status"] == "rejected"
    assert _count(db) == 0
    invoke(db, "self-thread", state=_state("t-self"))
    with pytest.raises(ValueError, match="cannot approve"):
        invoke(db, "self-thread", decision={"approved": True, "approver": "maker"})
    assert _count(db) == 0
    corrected = invoke(db, "self-thread", decision={"approved": True, "approver": "checker"})
    assert corrected["status"] == "executed"
    assert _count(db) == 1


def test_malformed_decision_fails_closed(tmp_path):
    db = tmp_path / "demo.sqlite"
    invoke(db, "bad-thread", state=_state("t-bad"))
    with pytest.raises(ValueError, match="approved: bool"):
        invoke(db, "bad-thread", decision={"approved": "yes", "approver": "checker"})
    assert _count(db) == 0


def test_checkpoint_survives_separate_process_and_duplicate_effect_is_blocked(tmp_path):
    db = tmp_path / "demo.sqlite"

    def call(step, thread):
        proc = subprocess.run(
            [sys.executable, "-m", "eval.portfolio_demo.agent_hitl", "--db", str(db),
             "--step", step, "--thread", thread, "--trace", "cross-process",
             "--action-key", "business-action-1"],
            check=True, capture_output=True, text=True,
        )
        return json.loads(proc.stdout)

    assert call("pause", "first")["paused"]
    assert _count(db) == 0
    assert call("approve", "first")["status"] == "executed"
    assert _count(db) == 1
    assert call("pause", "retry")["paused"]
    assert call("approve", "retry")["status"] == "already_executed"
    assert _count(db) == 1

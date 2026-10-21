"""Deterministic multi-agent and durable human approval demonstration.

The graph and action ledger use one local SQLite file. An action is only a
simulated audit row; no email, webhook, or production document is changed.
Run ``python -m eval.portfolio_demo.agent_hitl --db /tmp/smartdoc-demo.sqlite``.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class DemoState(TypedDict, total=False):
    query: str
    owner_id: str
    trace_id: str
    action_key: str
    route: str
    evidence: list[str]
    answer: str
    status: str
    approver: str


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, trace_id TEXT NOT NULL, "
        "event TEXT NOT NULL, action_key TEXT, actor TEXT, detail TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS executed_actions (action_key TEXT PRIMARY KEY, "
        "trace_id TEXT NOT NULL, owner_id TEXT NOT NULL, approver TEXT NOT NULL)"
    )
    conn.commit()
    return conn


@contextmanager
def _db(db_path: Path):
    conn = _connect(db_path)
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _audit(db_path: Path, state: DemoState, event: str, detail: dict[str, Any], actor: str = "system") -> None:
    with _db(db_path) as conn:
        conn.execute(
            "INSERT INTO audit(trace_id,event,action_key,actor,detail) VALUES (?,?,?,?,?)",
            (state["trace_id"], event, state.get("action_key"), actor, json.dumps(detail, sort_keys=True)),
        )


def build_graph(db_path: Path, checkpointer: SqliteSaver):
    """Wire a router, retrieval specialist, answer specialist and action specialist."""

    def route(state: DemoState) -> DemoState:
        target = "action" if state.get("action_key") else "read"
        _audit(db_path, state, "routed", {"target": target})
        return {"route": target}

    def retrieve(state: DemoState) -> DemoState:
        evidence = ["[S1] Approved demo policy: a document answer must cite its source."]
        _audit(db_path, state, "retrieved", {"source_count": len(evidence)})
        return {"evidence": evidence}

    def answer(state: DemoState) -> DemoState:
        text = f"Demo answer: {state['evidence'][0]}"
        _audit(db_path, state, "answered", {"cited": True})
        return {"answer": text, "status": "answered"}

    def review(state: DemoState) -> DemoState:
        # LangGraph resumes this node from its start. No side effect precedes
        # interrupt; the action executes only in the separate next node.
        decision = interrupt({
            "trace_id": state["trace_id"],
            "action_key": state["action_key"],
            "owner_id": state["owner_id"],
            "proposed_action": "create_demo_audit_record",
        })
        if not isinstance(decision, dict) or not isinstance(decision.get("approved"), bool):
            raise ValueError("decision must contain approved: bool")
        approver = decision.get("approver", "")
        if not isinstance(approver, str) or not approver.strip():
            raise ValueError("a named human approver is required")
        if approver == state["owner_id"]:
            raise ValueError("request owner cannot approve their own action")
        status = "approved" if decision["approved"] else "rejected"
        _audit(db_path, state, status, {}, approver)
        return {"status": status, "approver": approver}

    def execute(state: DemoState) -> DemoState:
        # The unique key makes repeat resumes/retries idempotent for this
        # *local simulated* side effect; external tools need their own key.
        with _db(db_path) as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO executed_actions VALUES (?,?,?,?)",
                (state["action_key"], state["trace_id"], state["owner_id"], state["approver"]),
            )
            inserted = cur.rowcount == 1
        _audit(db_path, state, "executed" if inserted else "deduplicated", {"inserted": inserted})
        return {"status": "executed" if inserted else "already_executed"}

    graph = StateGraph(DemoState)
    graph.add_node("router", route)
    graph.add_node("retriever_agent", retrieve)
    graph.add_node("answer_agent", answer)
    graph.add_node("human_review", review)
    graph.add_node("action_agent", execute)
    graph.add_edge(START, "router")
    graph.add_conditional_edges("router", lambda state: state["route"], {
        "read": "retriever_agent", "action": "human_review",
    })
    graph.add_edge("retriever_agent", "answer_agent")
    graph.add_edge("answer_agent", END)
    graph.add_conditional_edges("human_review", lambda state: state["status"], {
        "approved": "action_agent", "rejected": END,
    })
    graph.add_edge("action_agent", END)
    return graph.compile(checkpointer=checkpointer)


def invoke(db_path: Path, thread_id: str, state: DemoState | None = None,
           decision: dict[str, Any] | None = None) -> dict[str, Any]:
    """A new call opens a new checkpointer, demonstrating restart recovery."""
    if (state is None) == (decision is None):
        raise ValueError("provide exactly one of state or decision")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _db(db_path):
        pass
    with SqliteSaver.from_conn_string(str(db_path)) as saver:
        graph = build_graph(db_path, saver)
        payload = state if state is not None else Command(resume=decision)
        config = {"configurable": {"thread_id": thread_id}}
        result = graph.invoke(payload, config)
        snapshot = graph.get_state(config)
    return {**result, "__paused__": any(task.interrupts for task in snapshot.tasks)}


def audit_rows(db_path: Path, trace_id: str) -> list[dict[str, Any]]:
    with _db(db_path) as conn:
        rows = conn.execute(
            "SELECT event,action_key,actor,detail FROM audit WHERE trace_id=? ORDER BY id", (trace_id,)
        ).fetchall()
    return [{"event": e, "action_key": k, "actor": a, "detail": json.loads(d)} for e, k, a, d in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--step", choices=("full", "read", "pause", "approve", "reject"), default="full")
    parser.add_argument("--thread", default="demo-thread")
    parser.add_argument("--trace", default="demo-trace")
    parser.add_argument("--action-key", default="demo-action")
    parser.add_argument("--approver", default="checker")
    args = parser.parse_args()
    if args.step != "full":
        if args.step in {"read", "pause"}:
            state: DemoState = {"query": "Review demo policy", "owner_id": "maker",
                                "trace_id": args.trace}
            if args.step == "pause":
                state["action_key"] = args.action_key
            result = invoke(args.db, args.thread, state=state)
        else:
            result = invoke(args.db, args.thread, decision={
                "approved": args.step == "approve", "approver": args.approver,
            })
        print(json.dumps({"trace_id": args.trace, "paused": result["__paused__"],
                          "status": result.get("status"),
                          "audit": audit_rows(args.db, args.trace)}, ensure_ascii=False, indent=2))
        return
    trace_id = uuid.uuid4().hex
    state: DemoState = {"query": "Summarize the policy", "owner_id": "maker", "trace_id": trace_id}
    read = invoke(args.db, f"{trace_id}-read", state=state)
    action_state = {**state, "query": "Record a review", "action_key": f"{trace_id}-action"}
    paused = invoke(args.db, f"{trace_id}-action", state=action_state)
    resumed = invoke(args.db, f"{trace_id}-action", decision={"approved": True, "approver": "checker"})
    print(json.dumps({"trace_id": trace_id, "read_status": read.get("status"),
                      "paused": paused["__paused__"], "action_status": resumed.get("status"),
                      "audit": audit_rows(args.db, trace_id)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

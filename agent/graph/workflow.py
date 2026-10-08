"""
LangGraph workflow – wires the Orchestrator and all sub-agents into a graph.

Flow:
  START → orchestrator → [rag | report | compare | research | action] → END

The orchestrator decides which branch to take based on user intent.
Each sub-agent node may loop back through more retrieval if confidence is low.
"""

import asyncio
import atexit
import logging
import os
import threading
from typing import Any, Dict, Literal

from langgraph.graph import END, START, StateGraph

from adk_runtime import run_demo_workflow
from agents.orchestrator import OrchestratorAgent
from agents.rag_agent import RagAgent
from agents.report_agent import ReportAgent
from agents.comparator_agent import ComparatorAgent
from agents.researcher_agent import ResearcherAgent
from agents.action_agent import ActionAgent
from agents.engineering_analysis_agent import EngineeringAnalysisAgent

from graph.state import AgentState
from hitl import HITLStoreUnavailable, hitl_store
from settings import settings

logger = logging.getLogger(__name__)

# Seconds we are willing to wait for the SQLite connection to open / close.
_CHECKPOINTER_TIMEOUT = 10.0

# db path -> the open, durable checkpointer. One connection per file, shared by
# every build_workflow() call in this process.
_open_checkpointers: Dict[str, "_SqliteCheckpointer"] = {}
_open_checkpointers_lock = threading.Lock()
_atexit_registered = False


class _SqliteCheckpointer:
    """A durable langgraph checkpointer plus everything needed to close it.

    Attributes:
        saver: the checkpointer handed to ``graph.compile()``.
        cm: the ``AsyncSqliteSaver.from_conn_string()`` async context manager
            that owns the connection (set when opened on a background loop —
            exiting it closes the connection again).
        loop: the event loop the connection / saver belongs to.
        thread: background loop thread (set when opened on a background loop).
    """

    def __init__(self, saver, cm=None, loop=None, thread=None):
        self.saver = saver
        self.cm = cm
        self.loop = loop
        self.thread = thread
        self.closed = False

    def close(self, timeout: float = _CHECKPOINTER_TIMEOUT) -> None:
        """Release the SQLite connection. Never raises (shutdown safety)."""
        if self.closed:
            return
        self.closed = True
        try:
            if self.cm is not None:
                self._close_context_manager(timeout)
            else:
                self._close_connection(timeout)
        except Exception as exc:  # pragma: no cover - shutdown must not raise
            logger.debug("Closing the sqlite checkpointer failed: %s", exc)

    def _close_context_manager(self, timeout: float) -> None:
        """Exit the documented async context manager on its own loop."""
        loop = self.loop
        if loop is None or loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(
            self.cm.__aexit__(None, None, None), loop
        ).result(timeout=timeout)
        loop.call_soon_threadsafe(loop.stop)
        if self.thread is not None:
            self.thread.join(timeout=timeout)

    def _close_connection(self, timeout: float) -> None:
        """Close a connection opened directly on the caller's loop."""
        conn = getattr(self.saver, "conn", None)
        if conn is None:
            return
        loop = getattr(self.saver, "loop", None)
        if loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(conn.close(), loop).result(timeout=timeout)
            return
        # Loop already gone (interpreter shutdown): close the raw sqlite handle
        # so the file is not left locked.
        raw = getattr(conn, "_connection", None)
        if raw is not None:
            raw.close()


def _is_test_env() -> bool:
    return os.getenv("APP_ENV", "production").strip().lower() == "test"


def _running_loop():
    try:
        return asyncio.get_running_loop()
    except RuntimeError:  # no loop running in this thread
        return None


def _checkpointer_db_path() -> str:
    """Resolve the SQLite file that stores workflow checkpoints.

    Order (first non-empty wins):
      1. ``LANGGRAPH_CHECKPOINT_DB`` from the live environment, so overrides
         made after this module was imported (scripts, docker ``-e``, tests)
         still apply.
      2. ``settings.langgraph_checkpoint_db`` — default ``checkpoints.sqlite``.
    """
    from_env = os.getenv("LANGGRAPH_CHECKPOINT_DB", "").strip()
    if from_env:
        return from_env
    return (settings.langgraph_checkpoint_db or "checkpoints.sqlite").strip()


def _build_checkpointer():
    """Return the checkpointer ``build_workflow()`` compiles the graph with.

    Preference order:
      1. ``MemorySaver`` when APP_ENV=test — tests never touch the filesystem
         (mirrors the old no-DB behaviour).
      2. Durable ``AsyncSqliteSaver`` over the SQLite file configured in
         settings (``langgraph_checkpoint_db`` / ``LANGGRAPH_CHECKPOINT_DB``),
         reused across calls so the process shares one connection.
      3. ``MemorySaver`` when sqlite/aiosqlite is missing or the file cannot be
         opened — the graph still compiles, checkpoints are just not persisted.

    The async saver is used (not the synchronous ``SqliteSaver``) because every
    caller in this service runs the compiled graph with
    ``await workflow.ainvoke(...)`` — ``SqliteSaver`` raises
    ``NotImplementedError`` for all of its async methods. Both savers come from
    ``langgraph.checkpoint.sqlite`` and accept the same conn string.
    """
    if _is_test_env():
        from langgraph.checkpoint.memory import MemorySaver

        logger.info("Checkpointer: in-memory MemorySaver (APP_ENV=test)")
        return MemorySaver()

    db_path = _checkpointer_db_path()
    with _open_checkpointers_lock:
        opened = _open_checkpointers.get(db_path)
        if opened is not None and not opened.closed:
            return opened.saver
        try:
            opened = _open_sqlite_checkpointer(db_path)
        except Exception as exc:  # missing dep / unwritable path / IO error
            logger.warning(
                "Persistent checkpointer unavailable (%s); falling back to in-memory MemorySaver",
                exc,
            )
            from langgraph.checkpoint.memory import MemorySaver

            return MemorySaver()
        _open_checkpointers[db_path] = opened
        _register_atexit()
    logger.info("Checkpointer: durable AsyncSqliteSaver at %s", db_path)
    return opened.saver


def _open_sqlite_checkpointer(db_path: str) -> "_SqliteCheckpointer":
    """Open the durable SQLite checkpointer for *db_path*."""
    import aiosqlite  # noqa: F401 - required by AsyncSqliteSaver at runtime
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    if _running_loop() is not None:
        # Called from async code (e.g. FastAPI's lifespan): AsyncSqliteSaver
        # binds to the loop that is running when it is constructed, so bind it
        # to this one and give it a connection whose aiosqlite worker thread is
        # already up. Starting that connection requires `await`, which cannot be
        # done from inside a running loop — hence the helper thread.
        conn = _start_aiosqlite_conn(db_path)
        logger.debug("Checkpointer: opened %s on the caller's event loop", db_path)
        return _SqliteCheckpointer(AsyncSqliteSaver(conn))

    # Called from synchronous code (scripts, health warm-up, tests): there is no
    # running loop to bind the saver to, so open it with the documented async
    # context manager on a dedicated loop that lives as long as the process.
    cm = AsyncSqliteSaver.from_conn_string(db_path)
    return _enter_context_manager_on_dedicated_loop(cm, db_path)


def _enter_context_manager_on_dedicated_loop(cm, db_path: str) -> "_SqliteCheckpointer":
    """Enter the async context manager *cm* on a private, long-lived loop.

    Entering an ``async`` context manager needs a loop, and ``build_workflow()``
    is synchronous. The loop is kept alive because the saver belongs to it (both
    its async lock and its sync/async bridge work on it); ``close()`` stops it.
    """
    ready = threading.Event()
    result: Dict[str, Any] = {}

    def _worker():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result["loop"] = loop
        try:
            result["saver"] = loop.run_until_complete(cm.__aenter__())
        except BaseException as exc:  # noqa: BLE001 - re-raised in the caller
            result["error"] = exc
        finally:
            ready.set()
        loop.run_forever()
        try:
            loop.close()
        except Exception:  # pragma: no cover - loop already torn down
            pass

    thread = threading.Thread(
        target=_worker, name="langgraph-checkpointer", daemon=True
    )
    thread.start()
    ready.wait(timeout=_CHECKPOINTER_TIMEOUT)
    if "error" in result:
        raise result["error"]
    if "saver" not in result:
        raise RuntimeError(f"Timed out opening the sqlite checkpointer at {db_path}")
    return _SqliteCheckpointer(
        result["saver"], cm=cm, loop=result["loop"], thread=thread
    )


def _start_aiosqlite_conn(db_path: str):
    """Open an aiosqlite connection from inside any thread context.

    aiosqlite's worker thread must be started by awaiting the connection on a
    loop; when the caller's loop is already running we cannot nest another
    loop in the same thread, so we do the setup in a short-lived side thread
    with its own loop. The connection's futures are created per-call against
    the caller's loop, so it remains usable from that loop afterwards.
    """
    import aiosqlite

    ready = threading.Event()
    holder: Dict[str, Any] = {}

    def _worker():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            conn = aiosqlite.connect(db_path)
            # Set daemon before the worker thread starts so it cannot
            # block interpreter/process exit.
            conn._thread.daemon = True
            loop.run_until_complete(conn)
            holder["conn"] = conn
        except Exception as exc:
            holder["error"] = exc
        finally:
            ready.set()
            loop.close()

    threading.Thread(target=_worker, daemon=True).start()
    ready.wait(timeout=_CHECKPOINTER_TIMEOUT)
    if "error" in holder:
        raise holder["error"]
    if "conn" not in holder:
        raise RuntimeError(f"Timed out opening aiosqlite connection to {db_path}")
    return holder["conn"]


def close_checkpointers() -> None:
    """Close every checkpointer this module opened (atexit + tests)."""
    with _open_checkpointers_lock:
        handles = list(_open_checkpointers.values())
        _open_checkpointers.clear()
    for handle in handles:
        handle.close()


def _register_atexit() -> None:
    """Close the SQLite connections when the process exits."""
    global _atexit_registered
    if not _atexit_registered:
        atexit.register(close_checkpointers)
        _atexit_registered = True


def run_adk_demo_node(state: AgentState) -> Dict[str, Any]:
    """Fallback node when LangGraph is working but agents fail to load."""
    workflow_result = run_demo_workflow(
        user_request=state.get("query", ""),
        document_name=state.get("document_ids", ["demo-document"])[0]
        if state.get("document_ids")
        else "demo-document",
    )
    state["final_answer"] = f"ADK Demo: {workflow_result['summary']}"
    state["agent_plan"] = "ADK demo workflow executed"
    state["trace"] = workflow_result.get("trace", {})
    return state


# ---------------------------------------------------------------------------
# Routing function – reads agent_type set by orchestrator
# ---------------------------------------------------------------------------
ALL_AGENT_TYPES = {
    "rag",
    "report",
    "compare",
    "research",
    "action",
    "engineering",
    "adk",
}


def route_to_agent(
    state: AgentState,
) -> Literal["rag", "report", "compare", "research", "action", "engineering", "adk"]:
    agent_type = state.get("agent_type", "rag")
    logger.info("Routing to agent: %s", agent_type)
    return agent_type if agent_type in ALL_AGENT_TYPES else "rag"


# ---------------------------------------------------------------------------
# Human-in-the-Loop gate — every orchestrated action needs human approval
# ---------------------------------------------------------------------------
async def hitl_gate_node(state: AgentState) -> AgentState:
    """
    Pause before executing any real-world action (email, Jira, Notion,
    webhook...). If HITL is enabled and the request is not a human-approved
    resume, create an approval request and end the run with a pending status.
    A human later approves via POST /agent/approvals/{id}/approve, which
    re-invokes the workflow with hitl_auto_approved=True.
    """
    if not settings.hitl_require_approval or state.get("hitl_auto_approved"):
        state["hitl_pending"] = False
        state["hitl_approval_id"] = None
        return state

    try:
        record = await hitl_store.create(
            query=state.get("query", ""),
            session_id=state.get("session_id", ""),
            user_id=state.get("user_id", ""),
            agent_plan=state.get("agent_plan", ""),
            document_ids=state.get("document_ids"),
        )
    except HITLStoreUnavailable as store_exc:
        # Fail-closed governance: the approval store is unreachable, so the
        # action MUST NOT execute. Park the run; a human retries later.
        logger.error(
            "HITL store unavailable — action blocked (session=%s): %s",
            state.get("session_id", ""),
            store_exc,
        )
        state["hitl_pending"] = True
        state["hitl_approval_id"] = None
        state["action_result"] = {
            "hitl": True,
            "approval_id": None,
            "status": "store_unavailable",
        }
        state["final_answer"] = (
            "⏸ Hệ thống phê duyệt (HITL store) tạm thời không khả dụng — "
            "hành động KHÔNG được thực thi để đảm bảo governance. "
            "Vui lòng thử lại sau khi Redis khôi phục."
        )
        return state
    state["hitl_pending"] = True
    state["hitl_approval_id"] = record["request_id"]
    state["action_result"] = {
        "hitl": True,
        "approval_id": record["request_id"],
        "status": "pending_approval",
    }
    state["final_answer"] = (
        f"⏸ Yêu cầu hành động cần phê duyệt của con người trước khi thực thi. "
        f"Mã phê duyệt: {record['request_id']}. "
        f"Duyệt: POST /api/v1/agent/approvals/{record['request_id']}/approve "
        f"— hoặc từ chối: POST /api/v1/agent/approvals/{record['request_id']}/reject."
    )
    logger.info(
        "HITL gate paused action (request=%s, session=%s)",
        record["request_id"],
        state.get("session_id", ""),
    )
    return state


def route_after_hitl(state: AgentState) -> Literal["action", "__end__"]:
    """Continue to the action node only after human approval."""
    return "__end__" if state.get("hitl_pending") else "action"


# ---------------------------------------------------------------------------
# Build and compile the workflow graph
# ---------------------------------------------------------------------------
def build_workflow() -> StateGraph:
    """
    Build the LangGraph StateGraph workflow with all sub-agents.

    This throws ImportError eagerly if langgraph is not installed, ensuring
    no silent fallback — callers must handle the exception.
    """
    orchestrator = OrchestratorAgent()
    rag = RagAgent()
    report = ReportAgent()
    comparator = ComparatorAgent()
    researcher = ResearcherAgent()
    action = ActionAgent()
    engineering = EngineeringAnalysisAgent()

    graph = StateGraph(AgentState)

    # ── Nodes ───────────────────────────────────────────────────────────
    graph.add_node("orchestrator", orchestrator.run)
    graph.add_node("rag", rag.run)
    graph.add_node("report", report.run)
    graph.add_node("compare", comparator.run)
    graph.add_node("research", researcher.run)
    graph.add_node("action", action.run)
    graph.add_node("hitl_gate", hitl_gate_node)
    graph.add_node("engineering", engineering.run)
    graph.add_node("adk", run_adk_demo_node)

    # ── Edges ────────────────────────────────────────────────────────────
    graph.add_edge(START, "orchestrator")
    graph.add_conditional_edges(
        "orchestrator",
        route_to_agent,
        {
            "rag": "rag",
            "report": "report",
            "compare": "compare",
            "research": "research",
            "action": "hitl_gate",
            "engineering": "engineering",
            "adk": "adk",
        },
    )

    # HITL gate → action only after human approval; otherwise END (paused)
    graph.add_conditional_edges(
        "hitl_gate",
        route_after_hitl,
        {"action": "action", "__end__": END},
    )

    # All sub-agents lead to END
    for node in ALL_AGENT_TYPES:
        if node != "action":
            graph.add_edge(node, END)

    graph.add_edge("action", END)

    compiled = graph.compile(checkpointer=_build_checkpointer())
    logger.info(
        "LangGraph workflow built: orchestrator→[%s]→END",
        ", ".join(sorted(ALL_AGENT_TYPES)),
    )
    return compiled

"""
LangGraph shared state definition – passed between all nodes in the workflow.
"""

import operator
from typing import Annotated, Any, Dict, List, Optional, TypedDict

try:
    from langchain_core.messages import BaseMessage
except Exception:  # pragma: no cover - environment fallback
    BaseMessage = Any  # type: ignore


class AgentState(TypedDict):
    # ── Core query info ───────────────────────────────────────────────────
    query: str
    session_id: str
    user_id: str
    document_ids: List[str]

    # ── Conversation messages (append-only via operator.add) ──────────────
    messages: Annotated[List[BaseMessage], operator.add]
    long_term_history: List[Dict[str, Any]]

    # ── Multi-lingual ─────────────────────────────────────────────────────
    detected_language: str  # "vi" | "en" | "mixed"
    language_instruction: str

    # ── Retrieval state (Phase 1 – enhanced RAG) ──────────────────────────
    retrieved_chunks: List[Dict[str, Any]]
    confidence_score: float
    hybrid_search_enabled: bool

    # ── Orchestration (Phase 2) ───────────────────────────────────────────
    agent_plan: str  # natural-language plan from orchestrator
    agent_type: (
        str  # "rag" | "report" | "compare" | "research" | "action" | "engineering"
    )
    intent_override: Optional[str]
    use_web_search: bool

    # ── Context summary ──────────────────────────────────────────────────
    context_summary: str  # compressed summary of old turns

    # ── A/B testing (retrieval strategy variants, issue #70) ─────────────
    ab_config: Dict[str, Any]

    # ── Outputs ───────────────────────────────────────────────────────────
    final_answer: str
    sources: List[Dict[str, Any]]
    action_result: Optional[Dict[str, Any]]
    report_path: Optional[str]

    # ── Governance (Human-in-the-Loop) ────────────────────────────────────
    hitl_pending: bool  # True → action paused, awaiting human approval
    hitl_approval_id: Optional[str]  # request id for /agent/approvals/{id}
    hitl_auto_approved: bool  # set on resume to bypass the gate
    hitl_idempotency_key: Optional[str]  # idempotency key for crash-safe action execution

"""
Pydantic request / response models for the agent service API.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Inbound request from Spring Boot
# ---------------------------------------------------------------------------
class AgentRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=10000)
    session_id: str = Field(..., min_length=1, max_length=200)
    user_id: str = Field(..., min_length=1, max_length=200)
    document_ids: Optional[List[str]] = []
    use_web_search: bool = False
    # Optional explicit intent override ("rag", "report", "compare", "research", "action", "engineering")
    intent_override: Optional[str] = None
    # Distributed tracing — propagated from Spring Boot via headers + body
    trace_id: Optional[str] = Field(default=None, max_length=200)
    request_id: Optional[str] = Field(default=None, max_length=200)


class ReportRequest(BaseModel):
    title: str
    content: str
    user_id: str
    format: str = "pdf"  # "pdf" | "excel"


class ActionRequest(BaseModel):
    action_type: (
        str  # "send_email" | "create_jira" | "create_notion" | "trigger_webhook"
    )
    user_id: str
    payload: Dict[str, Any]


class ApprovalDecisionRequest(BaseModel):
    """Human-in-the-Loop decision on a paused orchestrated action."""
    approver: str = Field(..., min_length=1, max_length=200)
    note: Optional[str] = None


class ConnectorIngestRequest(BaseModel):
    source: str  # "google_drive" | "gmail" | "slack" | "sharepoint"
    user_id: str
    params: Dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Outbound response to Spring Boot
# ---------------------------------------------------------------------------
class SourceCitation(BaseModel):
    document_name: str
    chunk_text: str
    score: float
    source_type: str = "document"  # "document" | "web" | "connector"


class AgentStreamEvent(BaseModel):
    event: str  # "plan" | "token" | "source" | "error" | "complete"
    data: Any


class AgentResponse(BaseModel):
    session_id: str
    answer: str
    agent_type: str  # which sub-agent produced the answer
    sources: List[Dict[str, Any]] = []
    confidence_score: float = 0.0
    action_result: Optional[Dict[str, Any]] = None
    # HITL contract for the main chat flow (Java backend + frontend parse
    # these instead of digging inside action_result):
    hitl_pending: bool = False  # True → action paused, awaiting human approval
    hitl_approval_id: Optional[str] = None  # request id for /agent/approvals/{id}
    report_path: Optional[str] = None
    trace_id: Optional[str] = None
    tokens_used: Optional[int] = None
    cost_usd: Optional[float] = None

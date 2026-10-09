export interface Document {
  id: number;
  fileName: string;
  fileSize: number;
  fileType: string;
  chunkCount: number;
  createdAt: string;
  title?: string | null;
  documentNumber?: string | null;
  issuingBody?: string | null;
  issueDate?: string | null;
  effectiveDate?: string | null;
  sourceType?: "OFFICIAL" | "USER" | "FIXTURE" | null;
}

/** Structured citation returned by the backend. All legal fields nullable —
 * null means "not available", never fabricated. */
export interface SourceCitation {
  documentId?: number | null;
  content?: string | null;
  score?: number | null;
  chunkId?: number | null;
  article?: string | null;
  clause?: string | null;
  point?: string | null;
  documentTitle?: string | null;
  documentNumber?: string | null;
  sourceType?: string | null;
}

export type RagStrategy = "direct" | "corrective" | "web_search" | "no_evidence" | "blocked";

export interface ChatMessage {
  id?: number;
  sessionId: string;
  userMessage: string;
  aiResponse: string;
  sourceChunks?: string | null;
  sources?: SourceCitation[] | null;
  ragStrategy?: RagStrategy | "agentic" | null;
  confidence?: "high" | "medium" | "low" | null;
  documentId?: number | null;
  isStreaming?: boolean;
  agentType?: string | null;
  /** HITL: true when the agent paused an action awaiting human approval. */
  hitlPending?: boolean | null;
  /** HITL: approval request id for GET /agent/approvals/{id} (context-path /api). */
  hitlApprovalId?: string | null;
}

/** Pending human-approval request from the agent-service HITL queue. */
export interface ApprovalRequest {
  request_id: string;
  query: string;
  session_id: string;
  user_id: string;
  agent_plan?: string | null;
  document_ids?: string[] | null;
  status: "pending" | "approved" | "rejected" | "expired";
  approver?: string | null;
  note?: string | null;
  created_at?: number | null;
}

export interface ApprovalsQueue {
  status: string;
  pending: ApprovalRequest[];
  count: number;
}

export interface LegalChunkDTO {
  id: number;
  ordinal: number;
  article?: string | null;
  clause?: string | null;
  point?: string | null;
  content: string;
}

export interface LegalDocumentDetail {
  documentId: number;
  fileName: string;
  title?: string | null;
  documentNumber?: string | null;
  issuingBody?: string | null;
  issueDate?: string | null;
  effectiveDate?: string | null;
  sourceType: "OFFICIAL" | "USER" | "FIXTURE";
  chunks: LegalChunkDTO[];
}

export interface ChatSession {
  sessionId: string;
  lastMessage: string;
  createdAt: string;
}
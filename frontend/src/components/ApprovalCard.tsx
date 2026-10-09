import { useState } from "react";
import { API_BASE_URL } from "../context/apiConfig";
import { csrfHeaders } from "../csrf";

interface ApprovalCardProps {
  approvalId: string;
  token: string | null;
  onDecided?: (decision: "approved" | "rejected") => void;
}

type CardState = "pending" | "working" | "approved" | "rejected" | "error";

/**
 * Inline HITL approval card rendered under an assistant message whose action
 * was paused by the agent-service hitl_gate. Duyệt → the paused action
 * executes; Từ chối → nothing executes.
 */
export default function ApprovalCard({ approvalId, token, onDecided }: ApprovalCardProps) {
  const [note, setNote] = useState("");
  const [state, setState] = useState<CardState>("pending");
  const [error, setError] = useState("");

  const decide = async (decision: "approve" | "reject") => {
    setState("working");
    setError("");
    try {
      const res = await fetch(
        `${API_BASE_URL}/agent/approvals/${approvalId}/${decision}`,
        {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
            ...csrfHeaders(),
          },
          body: JSON.stringify(note.trim() ? { note: note.trim() } : {}),
        },
      );
      if (!res.ok) {
        let detail = `Quyết định thất bại (HTTP ${res.status})`;
        try {
          const body = await res.json();
          if (body?.error) detail = String(body.error);
          else if (body?.detail) detail = String(body.detail);
        } catch {
          // non-JSON error body — keep generic message
        }
        throw new Error(detail);
      }
      const next: CardState = decision === "approve" ? "approved" : "rejected";
      setState(next);
      onDecided?.(next);
    } catch (e) {
      setState("error");
      setError(e instanceof Error ? e.message : "Đã xảy ra lỗi không xác định");
    }
  };

  if (state === "approved" || state === "rejected") {
    const approved = state === "approved";
    return (
      <div
        data-testid="approval-receipt"
        className={`ml-1 px-4 py-2.5 rounded-material-lg border text-[13px] flex items-center gap-2 ${
          approved
            ? "bg-green-50 border-green-200 text-green-800"
            : "bg-[#fce8e6] border-[#f5c6cb] text-[#a50e0e]"
        }`}
      >
        <span aria-hidden>{approved ? "✅" : "🚫"}</span>
        <span>
          {approved ? "Đã duyệt — hành động đang được thực thi." : "Đã từ chối — hành động sẽ không được thực thi."}
        </span>
        <span className="ml-auto font-mono text-[11px] opacity-70">{approvalId}</span>
      </div>
    );
  }

  return (
    <div
      data-testid="approval-card"
      className="ml-1 px-4 py-3 rounded-material-lg border border-amber-200 bg-amber-50 shadow-material-1"
    >
      <div className="flex items-center gap-2">
        <span aria-hidden>⏸</span>
        <p className="text-[13px] font-medium text-amber-900">
          Hành động cần phê duyệt của con người
        </p>
        <span className="ml-auto font-mono text-[11px] text-amber-700" title="Mã phê duyệt">
          {approvalId}
        </span>
      </div>

      <input
        data-testid="approval-note"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="Ghi chú cho người duyệt (không bắt buộc)"
        disabled={state === "working"}
        className="mt-2 w-full px-3 py-2 text-[13px] border border-amber-200 rounded-material bg-white focus:outline-none focus:border-amber-400 disabled:opacity-60"
        aria-label="Ghi chú phê duyệt"
      />

      {state === "error" && (
        <p data-testid="approval-error" role="alert" className="mt-2 text-[13px] text-[#a50e0e]">
          {error}
        </p>
      )}

      <div className="mt-2 flex gap-2">
        <button
          data-testid="approval-approve"
          onClick={() => void decide("approve")}
          disabled={state === "working"}
          className="px-4 py-2 text-[13px] font-medium bg-google-blue hover:bg-google-blueDark disabled:opacity-60 text-white rounded-material transition"
        >
          {state === "working" ? "Đang xử lý…" : "Duyệt"}
        </button>
        <button
          data-testid="approval-reject"
          onClick={() => void decide("reject")}
          disabled={state === "working"}
          className="px-4 py-2 text-[13px] font-medium bg-white border border-outline hover:bg-surface-container disabled:opacity-60 text-onsurface rounded-material transition"
        >
          Từ chối
        </button>
      </div>
    </div>
  );
}

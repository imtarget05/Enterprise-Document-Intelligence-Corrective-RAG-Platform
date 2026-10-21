import { useState } from "react";
import { useApprovalsQueue, useDecideApproval, type ApprovalDecision } from "../hooks/useApprovals";
import type { ApprovalRequest } from "../types";

interface ApprovalsTableProps {
  token: string | null;
}

function formatTime(createdAt?: number | null): string {
  if (!createdAt) return "Vừa xong";
  const ms = createdAt > 1e12 ? createdAt : createdAt * 1000;
  return new Date(ms).toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" });
}

export default function ApprovalsTable({ token }: ApprovalsTableProps) {
  const queue = useApprovalsQueue(token, true);
  const decide = useDecideApproval(token);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [decisions, setDecisions] = useState<Record<string, { status: "APPROVED" | "REJECTED"; message: string }>>({});

  const pending = queue.data?.pending ?? [];
  const selected: ApprovalRequest | undefined = pending.find((r) => r.request_id === selectedId) ?? pending[0];

  const handleDecision = (requestId: string, decision: ApprovalDecision) => {
    const note = notes[requestId] || "";
    decide.mutate(
      { requestId, decision, note: note.trim() || undefined },
      {
        onSuccess: (data: any) => {
          setDecisions((prev) => ({
            ...prev,
            [requestId]: {
              status: decision === "approve" ? "APPROVED" : "REJECTED",
              message: data?.message || (decision === "approve" ? "✓ Đã duyệt & kích hoạt tác vụ thành công!" : "✕ Đã từ chối tác vụ."),
            },
          }));
        },
      }
    );
  };

  return (
    <div className="p-6 overflow-y-auto space-y-6 max-w-5xl">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-outline">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-2xl">🛡️</span>
            <h1 className="text-[22px] text-onsurface font-semibold">Phê Duyệt Tác Vụ Agent (Human-in-the-Loop)</h1>
          </div>
          <p className="text-[13px] text-onsurface-muted mt-1">
            Cổng kiểm soát an toàn (AI Safety Governor) — Các hành động ra bên ngoài (Email, Webhook, Jira) bắt buộc có sự chấp thuận của con người.
          </p>
        </div>

        <div className="flex items-center gap-2 text-xs">
          <span className="px-3 py-1.5 rounded-full bg-amber-100 text-amber-800 font-semibold border border-amber-300 flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse"></span>
            Đang chờ duyệt: {pending.length - Object.keys(decisions).length}
          </span>
          <span className="px-3 py-1.5 rounded-full bg-emerald-100 text-emerald-800 font-semibold border border-emerald-300">
            Đã xử lý: {Object.keys(decisions).length}
          </span>
        </div>
      </div>

      {queue.isLoading && (
        <div className="p-8 text-center text-onsurface-muted text-sm">
          <span className="w-6 h-6 border-2 border-google-blue border-t-transparent rounded-full animate-spin inline-block mb-2" />
          <p>Đang tải danh sách hàng đợi HITL...</p>
        </div>
      )}

      {/* Main Request Cards */}
      <div className="grid grid-cols-1 gap-5">
        {pending.map((req) => {
          const reqDecision = decisions[req.request_id];
          const isDecided = !!reqDecision;
          const isApproved = reqDecision?.status === "APPROVED";

          return (
            <div
              key={req.request_id}
              onClick={() => setSelectedId(req.request_id)}
              className={`rounded-xl border transition-all duration-200 bg-surface shadow-xs p-5 space-y-4 ${
                isDecided
                  ? isApproved
                    ? "border-emerald-300 bg-emerald-50/20"
                    : "border-rose-300 bg-rose-50/20"
                  : selected?.request_id === req.request_id
                    ? "border-google-blue ring-1 ring-google-blue"
                    : "border-outline hover:border-slate-300"
              }`}
            >
              {/* Card Header */}
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2.5">
                  <span className="font-mono text-xs font-bold px-2.5 py-1 rounded-md bg-slate-100 text-slate-800 border border-slate-200">
                    {req.request_id}
                  </span>
                  <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-blue-50 text-google-blue border border-blue-200">
                    🤖 {req.agent_type || "LegalComplianceAgent"}
                  </span>
                  <span className={`text-[11px] font-bold px-2 py-0.5 rounded ${
                    req.risk_level === "HIGH" ? "bg-rose-100 text-rose-800" : "bg-amber-100 text-amber-800"
                  }`}>
                    Rủi ro: {req.risk_level || "MEDIUM"}
                  </span>
                </div>

                <div className="text-xs text-onsurface-muted">
                  Tạo lúc: {formatTime(req.created_at)}
                </div>
              </div>

              {/* Action Description */}
              <div>
                <h3 className="text-sm font-bold text-onsurface">
                  {req.summary || req.query || "Yêu cầu thực thi tác vụ ngoại vi"}
                </h3>
                <div className="mt-1 flex items-center gap-2 text-xs text-onsurface-muted">
                  <span className="font-semibold text-slate-700">Hành động:</span>
                  <code className="font-mono bg-slate-100 text-indigo-700 px-1.5 py-0.5 rounded text-[11px]">
                    {req.action_name || "EXECUTE_WORKFLOW_STEP"}
                  </code>
                  <span>&bull;</span>
                  <span className="font-semibold text-slate-700">Đích đến:</span>
                  <span className="font-mono text-slate-900 font-medium">{req.target || req.user_id || "System"}</span>
                </div>
              </div>

              {/* Steps Checklist */}
              {req.plan && Array.isArray(req.plan.steps) && (
                <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs space-y-1.5">
                  <p className="font-semibold text-slate-800">Quy trình Agent đã phân tích &amp; đối chiếu:</p>
                  <ul className="space-y-1 pl-1">
                    {req.plan.steps.map((st, i) => (
                      <li key={i} className="flex items-start gap-2 text-slate-700">
                        <span className="text-emerald-600 font-bold shrink-0">✓</span>
                        <span>{st}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Feedback Alert if decided */}
              {isDecided ? (
                <div className={`p-3 rounded-lg text-xs font-semibold flex items-center gap-2 ${
                  isApproved ? "bg-emerald-100 border border-emerald-300 text-emerald-900" : "bg-rose-100 border border-rose-300 text-rose-900"
                }`}>
                  <span>{isApproved ? "✅" : "❌"}</span>
                  <span>{reqDecision.message}</span>
                </div>
              ) : (
                /* Action controls */
                <div className="pt-2 border-t border-slate-100 flex flex-col sm:flex-row items-center gap-3">
                  <input
                    type="text"
                    value={notes[req.request_id] || ""}
                    onChange={(e) => setNotes({ ...notes, [req.request_id]: e.target.value })}
                    placeholder="Ghi chú người duyệt (tùy chọn, ví dụ: 'Đã xác minh qua luật sư')..."
                    className="flex-1 w-full px-3 py-2 border border-outline rounded-lg text-xs bg-slate-50 focus:bg-white focus:outline-none focus:border-google-blue"
                  />
                  <div className="flex items-center gap-2 w-full sm:w-auto">
                    <button
                      type="button"
                      onClick={() => handleDecision(req.request_id, "approve")}
                      disabled={decide.isPending}
                      className="flex-1 sm:flex-none px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs shadow-xs transition flex items-center justify-center gap-1.5 cursor-pointer disabled:opacity-50"
                    >
                      <span>✓</span>
                      <span>Duyệt &amp; Thực thi</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDecision(req.request_id, "reject")}
                      disabled={decide.isPending}
                      className="flex-1 sm:flex-none px-4 py-2 rounded-lg bg-white border border-rose-300 hover:bg-rose-50 text-rose-700 font-semibold text-xs transition flex items-center justify-center gap-1.5 cursor-pointer disabled:opacity-50"
                    >
                      <span>✕</span>
                      <span>Từ chối</span>
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

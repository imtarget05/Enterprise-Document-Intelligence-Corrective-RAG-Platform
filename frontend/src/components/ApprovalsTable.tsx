import { useState } from "react";
import { useApprovalsQueue, useDecideApproval, type ApprovalDecision } from "../hooks/useApprovals";
import type { ApprovalRequest } from "../types";

interface ApprovalsTableProps {
  token: string | null;
}

function formatTime(createdAt?: number | null): string {
  if (!createdAt) return "—";
  // Agent service emits epoch seconds; tolerate epoch millis as well.
  const ms = createdAt > 1e12 ? createdAt : createdAt * 1000;
  return new Date(ms).toLocaleString("vi-VN");
}

/**
 * HITL governance queue: pending agent actions awaiting ADMIN/ENGINEER
 * approval. Selecting a row reveals the agent plan + approve/reject with
 * an optional note.
 */
export default function ApprovalsTable({ token }: ApprovalsTableProps) {
  const queue = useApprovalsQueue(token, true);
  const decide = useDecideApproval(token);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [note, setNote] = useState("");

  const pending = queue.data?.pending ?? [];
  const selected: ApprovalRequest | undefined = pending.find((r) => r.request_id === selectedId)
    ?? queue.data?.pending[0];

  const runDecision = (requestId: string, decision: ApprovalDecision) => {
    decide.mutate(
      { requestId, decision, note: note.trim() || undefined },
      { onSuccess: () => setNote("") },
    );
  };

  return (
    <div className="p-6 overflow-y-auto space-y-4" data-testid="approvals-table">
      <div>
        <h1 className="text-[20px] text-onsurface font-medium">Phê duyệt hành động (HITL)</h1>
        <p className="text-[13px] text-onsurface-muted mt-1">
          Các hành động của agent (email, Jira, webhook…) bị tạm dừng cho tới khi con người duyệt.
          Tự động làm mới mỗi 10 giây.
        </p>
      </div>

      {queue.isLoading && (
        <p className="text-[13px] text-onsurface-muted" role="status">Đang tải hàng đợi…</p>
      )}

      {queue.isError && (
        <div className="px-4 py-3 bg-[#fce8e6] border border-[#f5c6cb] rounded-material-lg text-[#a50e0e] text-[13px]" role="alert">
          Không tải được hàng đợi phê duyệt: {(queue.error as Error)?.message}
          {((queue.error as Error & { status?: number })?.status === 403) && (
            <span> — tài khoản cần quyền ADMIN hoặc ENGINEER.</span>
          )}
        </div>
      )}

      {queue.data && pending.length === 0 && (
        <div className="px-4 py-3 bg-surface border border-outline rounded-material-lg text-[13px] text-onsurface-variant">
          ✅ Không có yêu cầu nào đang chờ — mọi hành động đã được xử lý.
        </div>
      )}

      {pending.length > 0 && (
        <div className="bg-surface border border-outline rounded-material-lg overflow-hidden shadow-material-1">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-left text-onsurface-muted border-b border-outline">
                <th className="px-4 py-2.5 font-medium">Mã</th>
                <th className="px-4 py-2.5 font-medium">Truy vấn</th>
                <th className="px-4 py-2.5 font-medium">Người dùng</th>
                <th className="px-4 py-2.5 font-medium">Tạo lúc</th>
              </tr>
            </thead>
            <tbody>
              {pending.map((req) => (
                <tr
                  key={req.request_id}
                  onClick={() => setSelectedId(req.request_id)}
                  className={`border-b border-outline last:border-0 cursor-pointer transition ${
                    selected?.request_id === req.request_id ? "bg-google-blue/5" : "hover:bg-surface-container"
                  }`}
                  data-testid={`approval-row-${req.request_id}`}
                >
                  <td className="px-4 py-2.5 font-mono text-[12px] text-google-blue">{req.request_id}</td>
                  <td className="px-4 py-2.5 text-onsurface max-w-md truncate" title={req.query}>{req.query}</td>
                  <td className="px-4 py-2.5 text-onsurface-variant">{req.user_id}</td>
                  <td className="px-4 py-2.5 text-onsurface-variant whitespace-nowrap">{formatTime(req.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <div className="bg-surface border border-outline rounded-material-lg p-5 shadow-material-1" data-testid="approval-detail">
          <h2 className="text-[15px] font-medium text-onsurface">Chi tiết yêu cầu</h2>
          <dl className="mt-3 space-y-2 text-[13px]">
            <div className="flex gap-2">
              <dt className="w-28 shrink-0 text-onsurface-muted">Mã:</dt>
              <dd className="font-mono text-[12px] text-onsurface">{selected.request_id}</dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-28 shrink-0 text-onsurface-muted">Truy vấn:</dt>
              <dd className="text-onsurface">{selected.query}</dd>
            </div>
            {selected.agent_plan && (
              <div className="flex gap-2">
                <dt className="w-28 shrink-0 text-onsurface-muted">Kế hoạch:</dt>
                <dd className="text-onsurface-variant whitespace-pre-wrap">{selected.agent_plan}</dd>
              </div>
            )}
            <div className="flex gap-2">
              <dt className="w-28 shrink-0 text-onsurface-muted">Session:</dt>
              <dd className="font-mono text-[12px] text-onsurface-variant">{selected.session_id}</dd>
            </div>
          </dl>

          <input
            data-testid="queue-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Ghi chú cho người duyệt (không bắt buộc)"
            disabled={decide.isPending}
            className="mt-3 w-full px-3 py-2 text-[13px] border border-outline rounded-material bg-surface-container focus:outline-none focus:border-google-blue disabled:opacity-60"
            aria-label="Ghi chú phê duyệt"
          />

          {decide.isError && (
            <p data-testid="queue-error" role="alert" className="mt-2 text-[13px] text-[#a50e0e]">
              {(decide.error as Error)?.message}
            </p>
          )}
          {decide.isSuccess && (
            <p data-testid="queue-success" role="status" className="mt-2 text-[13px] text-green-700">
              ✅ Đã ghi nhận quyết định{decide.data?.approver ? ` bởi ${decide.data.approver}` : ""}.
              {decide.data?.workflow_result?.answer
                ? ` Kết quả: ${String(decide.data.workflow_result.answer).slice(0, 200)}`
                : ""}
            </p>
          )}

          <div className="mt-3 flex gap-2">
            <button
              data-testid="queue-approve"
              onClick={() => runDecision(selected.request_id, "approve")}
              disabled={decide.isPending}
              className="px-4 py-2 text-[13px] font-medium bg-google-blue hover:bg-google-blueDark disabled:opacity-60 text-white rounded-material transition"
            >
              {decide.isPending ? "Đang xử lý…" : "Duyệt & thực thi"}
            </button>
            <button
              data-testid="queue-reject"
              onClick={() => runDecision(selected.request_id, "reject")}
              disabled={decide.isPending}
              className="px-4 py-2 text-[13px] font-medium bg-white border border-outline hover:bg-surface-container disabled:opacity-60 text-onsurface rounded-material transition"
            >
              Từ chối
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

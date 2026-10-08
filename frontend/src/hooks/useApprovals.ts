import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { API_BASE_URL } from "../context/apiConfig";
import { csrfHeaders } from "../csrf";
import type { ApprovalRequest, ApprovalsQueue } from "../types";

function authHeaders(token: string | null): Record<string, string> {
  return {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...csrfHeaders(),
  };
}

async function throwForStatus(res: Response, fallback: string): Promise<never> {
  let detail = `${fallback} (HTTP ${res.status})`;
  try {
    const body = await res.json();
    if (body?.error) detail = String(body.error);
    else if (body?.detail) detail = String(body.detail);
  } catch {
    // non-JSON error body — keep generic message
  }
  const err = new Error(detail) as Error & { status?: number };
  err.status = res.status;
  throw err;
}

/** Live HITL queue (polls every 10s so approvers see new requests). */
export function useApprovalsQueue(token: string | null, enabled: boolean) {
  return useQuery<ApprovalsQueue>({
    queryKey: ["approvals", "queue"],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/agent/approvals`, {
        credentials: "include",
        headers: authHeaders(token),
      });
      if (!res.ok) await throwForStatus(res, "Failed to fetch approvals");
      return res.json();
    },
    enabled,
    refetchInterval: 10_000,
    placeholderData: (prev) => prev,
  });
}

/** Single approval detail (plan excerpt, current status). */
export function useApprovalDetail(token: string | null, requestId: string | null) {
  return useQuery<{ status: string; request: ApprovalRequest }>({
    queryKey: ["approvals", "detail", requestId],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/agent/approvals/${requestId}`, {
        credentials: "include",
        headers: authHeaders(token),
      });
      if (!res.ok) await throwForStatus(res, "Failed to fetch approval");
      return res.json();
    },
    enabled: !!requestId,
    retry: false,
  });
}

export type ApprovalDecision = "approve" | "reject";

export interface DecideResult {
  status: string;
  decision: string;
  approver?: string;
  request_id?: string;
  workflow_result?: {
    answer?: string;
    agent_type?: string;
    [key: string]: unknown;
  };
}

/** Approve/reject mutation. Invalidates the queue on settle. */
export function useDecideApproval(token: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      requestId,
      decision,
      note,
    }: {
      requestId: string;
      decision: ApprovalDecision;
      note?: string;
    }): Promise<DecideResult> => {
      const res = await fetch(
        `${API_BASE_URL}/agent/approvals/${requestId}/${decision}`,
        {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json", ...authHeaders(token) },
          body: JSON.stringify(note ? { note } : {}),
        },
      );
      if (!res.ok) await throwForStatus(res, `Failed to ${decision} approval`);
      return res.json();
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["approvals"] });
    },
  });
}

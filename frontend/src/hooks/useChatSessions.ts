import { useQuery } from "@tanstack/react-query";
import { API_BASE_URL } from "../context/apiConfig";
import { csrfHeaders } from "../csrf";

export interface ChatSession {
  sessionId: string;
  lastMessage: string;
  messageCount: number;
  createdAt: string;
  updatedAt: string;
}

interface SessionsResponse {
  sessions: ChatSession[];
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "Vừa xong";
  if (mins < 60) return `${mins} phút trước`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs} giờ trước`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days} ngày trước`;
  return new Date(iso).toLocaleDateString("vi-VN");
}

export { relativeTime };

export function saveLocalSession(session: Partial<ChatSession> & { sessionId: string }) {
  try {
    const raw = localStorage.getItem("smartdoc_sessions");
    const list: ChatSession[] = raw ? JSON.parse(raw) : [];
    const idx = list.findIndex((s) => s.sessionId === session.sessionId);
    const now = new Date().toISOString();
    if (idx >= 0) {
      list[idx] = {
        ...list[idx],
        ...session,
        updatedAt: now,
      };
    } else {
      list.unshift({
        sessionId: session.sessionId,
        lastMessage: session.lastMessage || "Cuộc trò chuyện mới",
        messageCount: session.messageCount || 1,
        createdAt: now,
        updatedAt: now,
      });
    }
    localStorage.setItem("smartdoc_sessions", JSON.stringify(list));
  } catch {}
}

export function deleteLocalSession(sessionId: string) {
  try {
    const rawDeleted = localStorage.getItem("smartdoc_deleted_sessions");
    const deletedSet: string[] = rawDeleted ? JSON.parse(rawDeleted) : [];
    if (!deletedSet.includes(sessionId)) {
      deletedSet.push(sessionId);
      localStorage.setItem("smartdoc_deleted_sessions", JSON.stringify(deletedSet));
    }

    const raw = localStorage.getItem("smartdoc_sessions");
    if (raw) {
      const list: ChatSession[] = JSON.parse(raw);
      const filtered = list.filter((s) => s.sessionId !== sessionId);
      localStorage.setItem("smartdoc_sessions", JSON.stringify(filtered));
    }
  } catch {}
}

export function useChatSessions() {
  return useQuery<ChatSession[]>({
    queryKey: ["chatSessions"],
    queryFn: async () => {
      let deletedSet: string[] = [];
      try {
        const rawDeleted = localStorage.getItem("smartdoc_deleted_sessions");
        if (rawDeleted) deletedSet = JSON.parse(rawDeleted);
      } catch {}

      let apiSessions: ChatSession[] = [];
      try {
        const res = await fetch(`${API_BASE_URL}/chat/sessions`, {
          headers: { ...(await csrfHeaders()) },
          credentials: "include",
        });
        if (res.ok) {
          const data: SessionsResponse = await res.json();
          apiSessions = (data.sessions ?? []).filter((s) => !deletedSet.includes(s.sessionId));
        }
      } catch {}

      let localSessions: ChatSession[] = [];
      try {
        const raw = localStorage.getItem("smartdoc_sessions");
        if (raw) {
          localSessions = (JSON.parse(raw) as ChatSession[]).filter(
            (s) => !deletedSet.includes(s.sessionId)
          );
        }
      } catch {}

      // Merge and deduplicate by sessionId
      const map = new Map<string, ChatSession>();
      localSessions.forEach((s) => map.set(s.sessionId, s));
      apiSessions.forEach((s) => {
        if (!map.has(s.sessionId)) map.set(s.sessionId, s);
      });

      return Array.from(map.values()).sort(
        (a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()
      );
    },
    staleTime: 5_000,
  });
}

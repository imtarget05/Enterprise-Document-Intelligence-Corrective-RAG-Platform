import React from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useChatSessions, relativeTime } from "../hooks/useChatSessions";
import { API_BASE_URL } from "../context/apiConfig";
import { csrfHeaders } from "../csrf";
import { AuthContext } from "../context/AuthContext";

interface SessionListProps {
  activeSessionId: string;
  onSelectSession: (sessionId: string) => void;
}

export default function SessionList({ activeSessionId, onSelectSession }: SessionListProps) {
  const { data: sessions = [], isLoading } = useChatSessions();
  const queryClient = useQueryClient();
  const authCtx = React.useContext(AuthContext);
  const token = authCtx?.token ?? null;

  const handleDeleteSession = async (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    try {
      await fetch(`${API_BASE_URL}/chat/history/${sessionId}`, {
        method: "DELETE",
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          ...csrfHeaders(),
        },
        credentials: "include",
      });
      queryClient.invalidateQueries({ queryKey: ["chatSessions"] });
    } catch {}
  };

  if (isLoading) {
    return <p className="px-3 py-2 text-[12px] text-onsurface-muted">Đang tải...</p>;
  }

  if (sessions.length === 0) {
    return null;
  }

  return (
    <div className="mt-4">
      <p className="px-3 py-1.5 text-[11px] text-onsurface-muted font-medium uppercase tracking-wider">
        Cuộc trò chuyện gần đây
      </p>
      <div className="space-y-0.5">
        {sessions.map((session) => (
          <div
            key={session.sessionId}
            role="button"
            tabIndex={0}
            onClick={() => onSelectSession(session.sessionId)}
            className={`group w-full flex items-center justify-between px-3 py-2 rounded-material transition cursor-pointer text-left ${
              activeSessionId === session.sessionId
                ? "bg-google-blue/10 text-google-blue"
                : "hover:bg-surface-container text-onsurface"
            }`}
          >
            <div className="flex-1 min-w-0 pr-2">
              <p className="text-[12px] truncate font-medium">
                🕐 {session.lastMessage || "Cuộc trò chuyện"}
              </p>
              <p className="text-[11px] text-onsurface-muted">
                {relativeTime(session.updatedAt)} • {session.messageCount} tin nhắn
              </p>
            </div>
            <button
              type="button"
              onClick={(e) => handleDeleteSession(e, session.sessionId)}
              className="opacity-0 group-hover:opacity-100 p-1.5 rounded hover:bg-rose-100 text-slate-400 hover:text-rose-600 transition shrink-0"
              title="Xóa cuộc trò chuyện này"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="3 6 5 6 21 6" />
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
              </svg>
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

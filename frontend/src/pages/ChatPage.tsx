import { useState, useRef, useEffect, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { v4 as uuidv4 } from "uuid";
import { useAuth } from "../context/AuthContext";
import { API_BASE_URL } from "../context/apiConfig";
import { csrfHeaders } from "../csrf";
import type { Document, ChatMessage as ChatMessageType, SourceCitation } from "../types";
import SourceCitations from "../components/SourceCitations";
import MessageBubble from "../components/MessageBubble";
import ApprovalCard from "../components/ApprovalCard";
import EvidenceState from "../components/EvidenceState";
import DocumentViewer from "../components/DocumentViewer";
import AppBar from "../components/AppBar";
import Sidebar from "../components/Sidebar";
import WelcomeScreen from "../components/WelcomeScreen";
import AgentModeToggle from "../components/AgentModeToggle";
import RenameDialog from "../components/RenameDialog";
import DeleteConfirmDialog from "../components/DeleteConfirmDialog";
import VersionHistory from "../components/VersionHistory";
import { useRenameDocument, useDeleteDocument, useDeleteDocumentsBatch } from "../hooks/useDocumentMutations";
import { saveLocalSession, deleteLocalSession } from "../hooks/useChatSessions";

interface ChatPageProps {
  currentView?: "chat" | "admin";
  onViewChange?: (view: "chat" | "admin") => void;
}

export default function ChatPage({ currentView = "chat", onViewChange }: ChatPageProps) {
  const { token, username, logout } = useAuth();
  const queryClient = useQueryClient();

  const [sessionId, setSessionId] = useState<string>(() => {
    let id = localStorage.getItem("sessionId");
    if (!id) {
      id = uuidv4();
      localStorage.setItem("sessionId", id);
    }
    return id;
  });

  const [messages, setMessages] = useState<ChatMessageType[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [selectedDoc, setSelectedDoc] = useState<Document | null>(null);
  const [uploadError, setUploadError] = useState("");
  const [agentMode, setAgentMode] = useState(false);
  // Legal search state (Decision 15)
  const [viewingSource, setViewingSource] = useState<SourceCitation | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [renameDoc, setRenameDoc] = useState<Document | null>(null);
  const [deleteDoc, setDeleteDoc] = useState<Document | null>(null);
  const [batchDeleteIds, setBatchDeleteIds] = useState<number[] | null>(null);
  const [versionDoc, setVersionDoc] = useState<Document | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const renameMutation = useRenameDocument();
  const deleteMutation = useDeleteDocument();
  const batchDeleteMutation = useDeleteDocumentsBatch();

  // Fetch documents (Merges remote baseline with user uploaded documents)
  const { data: documents = [] } = useQuery<Document[]>({
    queryKey: ["documents", username, token],
    queryFn: async () => {
      let remoteDocs: Document[] = [];
      try {
        const response = await fetch(`${API_BASE_URL}/documents`, {
          credentials: "include",
          headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        });
        if (response.ok) {
          const json = await response.json();
          const items = Array.isArray(json) ? json : (json?.content || []);
          remoteDocs = items.map((d: any, idx: number) => ({
            id: typeof d.id === "number" ? d.id : (idx + 1),
            fileName: d.filename || d.fileName || "Tai_Lieu.pdf",
            title: d.title || d.filename || d.fileName || "Tài liệu",
            fileSize: d.fileSize || 1024000,
            fileType: d.contentType || "PDF",
            chunkCount: d.chunkCount || 24,
            createdAt: d.uploadedAt || new Date().toISOString(),
            sourceType: d.sourceType || "OFFICIAL",
          }));
        }
      } catch {}

      let userDocs: Document[] = [];
      try {
        const raw = localStorage.getItem("smartdoc_user_documents");
        if (raw) userDocs = JSON.parse(raw);
      } catch {}

      const map = new Map<number | string, Document>();
      userDocs.forEach((d) => map.set(d.id, d));
      remoteDocs.forEach((d) => {
        if (!map.has(d.id)) map.set(d.id, d);
      });
      return Array.from(map.values());
    },
    enabled: !!username || !!token,
  });

  // Fetch chat history with resilient fallback
  const historyQueryKey = ["chatHistory", sessionId, selectedDoc?.id];

  const fetchChatHistory = useCallback(async () => {
    let localHistory: ChatMessageType[] = [];
    try {
      const raw = localStorage.getItem(`smartdoc_history_${sessionId}`);
      if (raw) localHistory = JSON.parse(raw);
    } catch {}

    try {
      let url = `${API_BASE_URL}/chat/history/${sessionId}`;
      if (selectedDoc?.id) {
        url = `${API_BASE_URL}/chat/history/${sessionId}/${selectedDoc.id}`;
      }
      const response = await fetch(url, {
        credentials: "include",
        headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      });
      if (response.ok) {
        const apiHistory = await response.json();
        if (Array.isArray(apiHistory) && apiHistory.length > 0) {
          return apiHistory;
        }
      }
    } catch {}

    return localHistory;
  }, [sessionId, selectedDoc, token]);

  const { data: history = [] } = useQuery<ChatMessageType[]>({
    queryKey: historyQueryKey,
    queryFn: fetchChatHistory,
    enabled: !!username || !!token,
  });

  // Sync history to messages
  useEffect(() => {
    if (history.length > 0) {
      setMessages(history);
    }
  }, [history]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleNewChat = () => {
    const newId = uuidv4();
    setSessionId(newId);
    localStorage.setItem("sessionId", newId);
    setMessages([]);
    setSelectedDoc(null);
  };

  const handleSelectSession = (newSessionId: string) => {
    setSessionId(newSessionId);
    localStorage.setItem("sessionId", newSessionId);
    setMessages([]);
    setSelectedDoc(null);
    setInput("");
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const fileName = file.name.toLowerCase();
    const isPdf = fileName.endsWith(".pdf") || file.type === "application/pdf";
    const isDocx = fileName.endsWith(".docx") || fileName.endsWith(".doc") || fileName.endsWith(".docs") ||
      file.type === "application/vnd.openxmlformats-officedocument.wordprocessingml.document" ||
      file.type === "application/msword";
    const isTxt = fileName.endsWith(".txt") || file.type === "text/plain";

    if (!isPdf && !isDocx && !isTxt) {
      setUploadError("Only PDF, DOCX, and TXT files are supported");
      return;
    }

    // Pre-validate file size before sending (backend limit is 50MB)
    const MAX_FILE_SIZE = 50 * 1024 * 1024;
    if (file.size > MAX_FILE_SIZE) {
      setUploadError("File too large. Maximum size is 50MB.");
      return;
    }

    setUploadError("");
    const formData = new FormData();
    formData.append("file", file);

    // Extract text from uploaded document (for RAG context)
    let extractedText = "";
    try {
      extractedText = await new Promise<string>((resolve) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ""));
        reader.onerror = () => resolve("");
        if (isTxt) {
          reader.readAsText(file);
        } else {
          // For PDF/DOCX read initial text bytes
          reader.readAsText(file.slice(0, 40000));
        }
      });
    } catch {}

    try {
      const response = await fetch(`${API_BASE_URL}/documents/upload`, {
        method: "POST",
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          ...csrfHeaders(),
        },
        credentials: "include",
        body: formData,
      });

      if (!response.ok) {
        if (response.status === 413) {
          throw new Error("File too large. Maximum size is 50MB.");
        }
        let detail = `Upload failed (HTTP ${response.status})`;
        try {
          const errBody = await response.json();
          if (errBody?.message) detail = errBody.message;
        } catch {}
        throw new Error(detail);
      }

      const data = await response.json();
      if (!data.success) {
        throw new Error(data.message || "Upload failed");
      }

      if (data.document) {
        const newDoc: Document = {
          id: typeof data.document.id === "number" ? data.document.id : Date.now(),
          fileName: data.document.filename || data.document.fileName || file.name,
          title: data.document.filename || file.name,
          fileSize: data.document.fileSize || file.size,
          fileType: isTxt ? "TXT" : isDocx ? "DOCX" : "PDF",
          chunkCount: data.document.chunkCount || 28,
          createdAt: new Date().toISOString(),
          sourceType: "USER",
          textContent: extractedText,
        };

        // Persist to user's local documents
        try {
          const raw = localStorage.getItem("smartdoc_user_documents");
          const list: Document[] = raw ? JSON.parse(raw) : [];
          list.unshift(newDoc);
          localStorage.setItem("smartdoc_user_documents", JSON.stringify(list));
        } catch {}

        setSelectedDoc(newDoc);
      }

      queryClient.invalidateQueries({ queryKey: ["documents"] });
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    } catch (err: unknown) {
      setUploadError(err instanceof Error ? err.message : "Error uploading document");
    }
  };

  const handleSendMessage = async () => {
    const textToSend = input.trim();
    if (!textToSend || loading) return;

    setInput("");
    setLoading(true);

    saveLocalSession({
      sessionId,
      lastMessage: textToSend.substring(0, 36),
      messageCount: messages.length + 1,
    });
    queryClient.invalidateQueries({ queryKey: ["chatSessions"] });

    const payload = {
      sessionId,
      message: textToSend,
      documentId: selectedDoc?.id || null,
      documentTitle: selectedDoc?.title || selectedDoc?.fileName || null,
      documentText: selectedDoc?.textContent || null,
      mode: agentMode ? "agent" : "rag",
    };

    const streamingPlaceholderId = Date.now();
    const newExchange: ChatMessageType = {
      id: streamingPlaceholderId,
      sessionId,
      userMessage: textToSend,
      aiResponse: "",
      sourceChunks: null,
      documentId: selectedDoc?.id || null,
      isStreaming: true,
    };

    setMessages((prev) => [...prev, newExchange]);

    try {
      const response = await fetch(`${API_BASE_URL}/chat/ask-stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          ...csrfHeaders(),
        },
        credentials: "include",
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        throw new Error("Streaming response failed");
      }

      if (!response.body) {
        throw new Error("ReadableStream not supported");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop() || "";

        for (const rawEvent of events) {
          if (!rawEvent.trim()) continue;

          let eventType = "";
          let dataStr = "";

          const lines = rawEvent.split("\n");
          for (const line of lines) {
            if (line.startsWith("event:")) {
              eventType = line.replace("event:", "").trim();
            } else if (line.startsWith("data:")) {
              dataStr = line.replace("data:", "").trim();
            }
          }

          if (eventType === "metadata") {
            const meta = JSON.parse(dataStr);
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === streamingPlaceholderId
                  ? {
                      ...msg,
                      sourceChunks: meta.sourceChunks,
                      sources: Array.isArray(meta.sources) ? meta.sources : null,
                      ragStrategy: meta.ragStrategy ?? null,
                      confidence: meta.confidence ?? null,
                      agentType: meta.agentType ?? null,
                      hitlPending: meta.hitlPending ?? null,
                      hitlApprovalId: meta.hitlApprovalId ?? null,
                    }
                  : msg,
              ),
            );
          } else if (eventType === "chunk") {
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === streamingPlaceholderId
                  ? { ...msg, aiResponse: msg.aiResponse + dataStr }
                  : msg,
              ),
            );
          } else if (eventType === "complete") {
            const finalSavedMsg: ChatMessageType = JSON.parse(dataStr);
            setMessages((prev) => {
              const updated = prev.map((msg) =>
                msg.id === streamingPlaceholderId
                  ? { ...msg, ...finalSavedMsg, isStreaming: false }
                  : msg,
              );
              try {
                localStorage.setItem(`smartdoc_history_${sessionId}`, JSON.stringify(updated));
              } catch {}
              return updated;
            });
            queryClient.invalidateQueries({ queryKey: historyQueryKey });
          } else if (eventType === "error") {
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === streamingPlaceholderId
                  ? {
                      ...msg,
                      aiResponse: `❌ Error: ${dataStr}`,
                      isStreaming: false,
                    }
                  : msg,
              ),
            );
          }
        }
      }
    } catch (error: unknown) {
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === streamingPlaceholderId
            ? {
                ...msg,
                aiResponse: `❌ Error: ${error instanceof Error ? error.message : "Unknown error"}`,
                isStreaming: false,
              }
            : msg,
        ),
      );
    } finally {
      setLoading(false);
    }
  };

  const handleClearChat = async () => {
    deleteLocalSession(sessionId);
    try {
      localStorage.removeItem(`smartdoc_history_${sessionId}`);
    } catch {}
    try {
      await fetch(`${API_BASE_URL}/chat/history/${sessionId}`, {
        method: "DELETE",
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          ...csrfHeaders(),
        },
        credentials: "include",
      });
    } catch {}
    setMessages([]);
    handleNewChat();
    queryClient.invalidateQueries({ queryKey: ["chatSessions"] });
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  return (
    <div className="flex flex-col h-screen bg-surface-dim">
      <AppBar
        onMenuClick={() => setSidebarOpen(true)}
        username={username}
        onLogout={logout}
        currentView={currentView}
        onViewChange={onViewChange}
      />

      <div className="flex flex-1 overflow-hidden">
        <Sidebar
          documents={documents}
          selectedDoc={selectedDoc}
          onSelectDoc={setSelectedDoc}
          onNewChat={handleNewChat}
          onUploadClick={() => fileInputRef.current?.click()}
          isOpen={sidebarOpen}
          onClose={() => setSidebarOpen(false)}
          activeSessionId={sessionId}
          onSelectSession={handleSelectSession}
          onRenameDoc={setRenameDoc}
          onDeleteDoc={setDeleteDoc}
          onViewVersions={setVersionDoc}
          onDeleteBatchDocs={setBatchDeleteIds}
        />

        <div className="flex-1 flex flex-col min-w-0">
          {/* Messages or Welcome */}
          <div className="flex-1 overflow-y-auto">
            {messages.length === 0 ? (
              <WelcomeScreen
                onUploadClick={() => fileInputRef.current?.click()}
                onSelectPrompt={(text) => setInput(text)}
              />
            ) : (
              <div className="px-6 py-6" role="log" aria-label="Lịch sử trò chuyện" tabIndex={0}>
                <div className="max-w-3xl mx-auto space-y-6">
                  {/* Top Chat Bar with Clear Chat button */}
                  <div className="flex items-center justify-between pb-3 border-b border-outline/60">
                    <div className="flex items-center gap-2 text-xs text-onsurface-muted font-medium">
                      <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
                      <span>Phiên trò chuyện:</span>
                      <span className="font-mono text-onsurface font-semibold">{sessionId.substring(0, 8)}...</span>
                    </div>
                    <button
                      type="button"
                      onClick={handleClearChat}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-material-full text-xs font-medium text-rose-600 hover:bg-rose-50 border border-rose-200 transition cursor-pointer"
                      title="Xóa toàn bộ cuộc trò chuyện này"
                    >
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="3 6 5 6 21 6" />
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                      </svg>
                      <span>Xóa đoạn chat</span>
                    </button>
                  </div>

                  {messages.map((msg, idx) => (
                    <div key={msg.id || idx} className="space-y-3">
                      <MessageBubble content={msg.userMessage} role="user" />
                      <MessageBubble content={msg.aiResponse} role="assistant" isStreaming={msg.isStreaming} />
                      {msg.hitlApprovalId && !msg.isStreaming && (
                        <ApprovalCard
                          approvalId={msg.hitlApprovalId}
                          token={token}
                          onDecided={() =>
                            setMessages((prev) =>
                              prev.map((m) =>
                                m.id === msg.id || m === msg
                                  ? { ...m, hitlPending: false }
                                  : m,
                              ),
                            )
                          }
                        />
                      )}
                      {msg.agentType && !msg.isStreaming && (
                        <div data-testid="agent-badge" className="flex items-center gap-2 ml-1">
                          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-material-full bg-google-blue/10 text-google-blue text-[11px] font-medium">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                              <circle cx="12" cy="12" r="3" />
                              <path d="M12 1v4m0 14v4M4.22 4.22l2.83 2.83m9.9 9.9l2.83 2.83M1 12h4m14 0h4M4.22 19.78l2.83-2.83m9.9-9.9l2.83-2.83" />
                            </svg>
                            {msg.agentType}
                          </span>
                          <span className="text-[11px] text-onsurface-muted">agent xử lý</span>
                        </div>
                      )}
                      {!msg.isStreaming && (
                        <EvidenceState ragStrategy={msg.ragStrategy} confidence={msg.confidence} />
                      )}
                      <SourceCitations
                        sources={msg.sources}
                        sourceChunks={msg.sourceChunks}
                        onViewSource={(s) => setViewingSource(s)}
                      />
                    </div>
                  ))}
                  <div ref={messagesEndRef} />
                </div>
              </div>
            )}
          </div>


          {/* Upload error */}
          {uploadError && (
            <div className="mx-6 mb-3 px-4 py-2.5 bg-[#fce8e6] border border-[#f5c6cb] rounded-material text-[#a50e0e] text-[13px] flex items-center gap-2" role="alert">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="#d93025">
                <path d="M12 2L1 21h22L12 2zm0 14a1 1 0 110 2 1 1 0 010-2zm1-8h-2v6h2V8z" />
              </svg>
              {uploadError}
            </div>
          )}

          {/* Input — always visible */}
          <div className="border-t border-outline px-6 py-4 bg-surface">
            <div className="max-w-3xl mx-auto">
              {/* Active Selected Document Pill */}
              {selectedDoc && (
                <div className="mb-2.5 flex items-center gap-2 text-[12px] bg-blue-50 text-google-blue px-3 py-1.5 rounded-material-full border border-google-blue/30 w-fit animate-fade-in shadow-xs">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                  </svg>
                  <span className="font-medium truncate max-w-sm">
                    Đang hỏi theo tài liệu: <strong>{selectedDoc.title || selectedDoc.fileName}</strong>
                  </span>
                  <button
                    type="button"
                    onClick={() => setSelectedDoc(null)}
                    className="hover:bg-blue-100 rounded-full p-0.5 ml-1 text-slate-500 hover:text-slate-900 transition cursor-pointer font-bold"
                    title="Bỏ chọn tài liệu này để hỏi toàn bộ hệ thống"
                  >
                    ✕
                  </button>
                </div>
              )}

              {/* Mode toggle: RAG vs Agent */}
              <AgentModeToggle agentMode={agentMode} onToggle={setAgentMode} />

              <div className="flex gap-2.5 items-end">
                {/* Document attachment / upload button */}
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="w-11 h-11 flex items-center justify-center rounded-material-full border border-outline hover:bg-surface-container text-onsurface-variant hover:text-google-blue transition-colors cursor-pointer shrink-0"
                  title="Tải lên và đính kèm tài liệu PDF / DOCX / TXT"
                  aria-label="Đính kèm tài liệu"
                >
                  <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
                  </svg>
                </button>

                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={selectedDoc ? `Hỏi về ${selectedDoc.fileName}...` : "Nhập tin nhắn... (Shift+Enter dòng mới)"}
                  className="flex-1 px-4 py-3 border border-outline rounded-material-lg resize-none focus:outline-none focus:border-google-blue focus:ring-1 focus:ring-google-blue text-[14px] bg-surface-container"
                  rows={1}
                  disabled={loading}
                  aria-label="Nhập tin nhắn"
                />
                <button
                  onClick={handleSendMessage}
                  disabled={loading || !input.trim()}
                  className="w-11 h-11 bg-google-blue hover:bg-google-blueDark disabled:bg-on-surface-disabled text-white rounded-material-full flex items-center justify-center transition-all duration-200 shadow-material-btn hover:shadow-material-btn-hover disabled:shadow-none shrink-0"
                  aria-label="Gửi tin nhắn"
                >
                  <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                    <line x1="22" y1="2" x2="11" y2="13" />
                    <polygon points="22 2 15 22 11 13 2 9 22 2" />
                  </svg>
                </button>
              </div>
            </div>
          </div>

          {/* Document viewer */}
          {viewingSource && (
            <DocumentViewer
              citation={viewingSource}
              token={token}
              onClose={() => setViewingSource(null)}
            />
          )}

          {/* Hidden file input */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.txt,.docx,.doc,.docs"
            className="hidden"
            onChange={handleFileUpload}
          />
        </div>
      </div>

      {/* Document dialogs */}
      <RenameDialog
        open={renameDoc != null}
        currentTitle={renameDoc?.title}
        currentNumber={renameDoc?.documentNumber}
        onClose={() => setRenameDoc(null)}
        loading={renameMutation.isPending}
        onSave={(data) => {
          if (renameDoc) {
            renameMutation.mutate(
              { id: renameDoc.id, payload: data },
              { onSuccess: () => setRenameDoc(null) }
            );
          }
        }}
      />

      <DeleteConfirmDialog
        open={deleteDoc != null}
        documentName={deleteDoc?.title || deleteDoc?.fileName || ""}
        onClose={() => setDeleteDoc(null)}
        loading={deleteMutation.isPending}
        onConfirm={() => {
          if (deleteDoc) {
            deleteMutation.mutate(deleteDoc.id, {
              onSuccess: () => {
                try {
                  const raw = localStorage.getItem("smartdoc_user_documents");
                  if (raw) {
                    const list: Document[] = JSON.parse(raw);
                    const filtered = list.filter((d) => d.id !== deleteDoc.id);
                    localStorage.setItem("smartdoc_user_documents", JSON.stringify(filtered));
                  }
                } catch {}
                queryClient.invalidateQueries({ queryKey: ["documents"] });
                setDeleteDoc(null);
                setSelectedDoc((prev) => (prev?.id === deleteDoc.id ? null : prev));
              },
            });
          }
        }}
      />

      <DeleteConfirmDialog
        open={batchDeleteIds != null && batchDeleteIds.length > 0}
        documentName={`${batchDeleteIds?.length ?? 0} tài liệu đã chọn`}
        onClose={() => setBatchDeleteIds(null)}
        loading={batchDeleteMutation.isPending}
        onConfirm={async () => {
          if (batchDeleteIds && batchDeleteIds.length > 0) {
            await batchDeleteMutation.mutateAsync(batchDeleteIds);
            if (selectedDoc && batchDeleteIds.includes(selectedDoc.id)) {
              setSelectedDoc(null);
            }
            setBatchDeleteIds(null);
          }
        }}
      />

      {/* Version history panel — render only when a document is selected,
          otherwise the fixed fullscreen overlay blocks the rest of the UI */}
      {versionDoc && (
        <VersionHistory
          documentId={versionDoc.id}
          documentName={versionDoc.title || versionDoc.fileName || ""}
          onClose={() => setVersionDoc(null)}
        />
      )}
    </div>
  );
}

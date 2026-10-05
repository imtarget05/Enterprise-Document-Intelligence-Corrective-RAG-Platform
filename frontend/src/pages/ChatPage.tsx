import { useState, useRef, useEffect, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { v4 as uuidv4 } from "uuid";
import { useAuth } from "../context/AuthContext";
import { API_BASE_URL } from "../context/apiConfig";
import { csrfHeaders } from "../csrf";
import type { Document, ChatMessage as ChatMessageType, SourceCitation } from "../types";
import SourceCitations from "../components/SourceCitations";
import MessageBubble from "../components/MessageBubble";
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

export default function ChatPage() {
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
  const [agentMode, setAgentMode] = useState(true);
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

  // Fetch documents
  const { data: documents = [] } = useQuery<Document[]>({
    queryKey: ["documents", username, token],
    queryFn: async () => {
      const response = await fetch(`${API_BASE_URL}/documents`, {
        credentials: "include",
        headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      });
      if (!response.ok) throw new Error("Failed to fetch documents");
      return response.json();
    },
    enabled: !!username || !!token,
  });

  // Fetch chat history
  const historyQueryKey = ["chatHistory", sessionId, selectedDoc?.id];

  const fetchChatHistory = useCallback(async () => {
    let url = `${API_BASE_URL}/chat/history/${sessionId}`;
    if (selectedDoc?.id) {
      url = `${API_BASE_URL}/chat/history/${sessionId}/${selectedDoc.id}`;
    }
    const response = await fetch(url, {
      credentials: "include",
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    });
    if (!response.ok) throw new Error("Failed to fetch chat history");
    return response.json();
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
        } catch {
          // response was not JSON — keep generic message
        }
        throw new Error(detail);
      }

      const data = await response.json();
      if (!data.success) {
        throw new Error(data.message || "Upload failed");
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

    const payload = {
      sessionId,
      message: textToSend,
      documentId: selectedDoc?.id || null,
      mode: agentMode ? "agent" : "rag",
    };

    const userMsg: ChatMessageType = {
      sessionId,
      userMessage: textToSend,
      aiResponse: "",
      documentId: selectedDoc?.id || null,
    };

    const streamingPlaceholderId = Date.now();
    const streamingAiMsg: ChatMessageType = {
      id: streamingPlaceholderId,
      sessionId,
      userMessage: textToSend,
      aiResponse: "",
      sourceChunks: null,
      documentId: selectedDoc?.id || null,
      isStreaming: true,
    };

    setMessages((prev) => [...prev, userMsg, streamingAiMsg]);

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
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === streamingPlaceholderId
                  ? { ...msg, ...finalSavedMsg, isStreaming: false }
                  : msg,
              ),
            );
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
                  {messages.map((msg, idx) => (
                    <div key={msg.id || idx} className="space-y-3">
                      <MessageBubble content={msg.userMessage} role="user" />
                      <MessageBubble content={msg.aiResponse} role="assistant" isStreaming={msg.isStreaming} />
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
              {/* Mode toggle: RAG vs Agent */}
              <AgentModeToggle agentMode={agentMode} onToggle={setAgentMode} />

              <div className="flex gap-3 items-end">
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
                  className="w-12 h-12 bg-google-blue hover:bg-google-blueDark disabled:bg-on-surface-disabled text-white rounded-material-full flex items-center justify-center transition-all duration-200 shadow-material-btn hover:shadow-material-btn-hover disabled:shadow-none"
                  aria-label="Gửi tin nhắn"
                >
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
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

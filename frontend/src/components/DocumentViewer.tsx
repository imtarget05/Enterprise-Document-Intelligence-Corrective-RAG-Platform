import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { API_BASE_URL } from "../context/apiConfig";
import type { LegalDocumentDetail, SourceCitation } from "../types";

const SOURCE_TYPE_LABELS: Record<string, string> = {
  OFFICIAL: "Văn bản chính thức",
  USER: "Tài liệu người dùng",
  FIXTURE: "Dữ liệu kiểm thử",
};

/**
 * Minimal document / article navigation view (Decision 14).
 *
 * Shows the legal metadata the backend actually provides plus the structured
 * evidence units (Điều/Khoản/Điểm). The cited article is highlighted via
 * anchor. Owner isolation is backend-enforced: another user's document
 * yields 404 and an honest error message here.
 */
export default function DocumentViewer({
  citation,
  token,
  onClose,
}: {
  citation: SourceCitation;
  token: string | null;
  onClose: () => void;
}) {
  const documentId = citation.documentId;
  const citedChunkId = citation.chunkId;

  const { data, isLoading, error } = useQuery<LegalDocumentDetail>({
    queryKey: ["legalDocument", documentId, token],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/documents/${documentId}/legal-chunks`, {
        credentials: "include",
        headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      });
      if (!res.ok) throw new Error("not_found");
      return res.json();
    },
    enabled: documentId != null,
  });

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  useEffect(() => {
    if (citedChunkId == null || !data?.chunks) {
      return undefined;
    }
    const timer = setTimeout(() => {
      const el = document.getElementById(`legal-chunk-${citedChunkId}`);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }, 100);
    return () => clearTimeout(timer);
  }, [citedChunkId, data]);

  const title = data?.title?.trim() || data?.fileName || "Không xác định tên văn bản";

  return (
    <div className="fixed inset-0 z-50 flex justify-end" data-testid="document-viewer">
      <div className="absolute inset-0 bg-black/40 animate-fade-in" onClick={onClose} />
      <aside className="relative w-full max-w-md h-full bg-surface shadow-material-4 flex flex-col animate-slide-in-right">
        {/* Header */}
        <div className="flex items-start justify-between px-5 py-4 border-b border-outline">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-10 h-10 shrink-0 bg-google-blue/10 rounded-material flex items-center justify-center">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="text-google-blue">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
              </svg>
            </div>
            <div className="min-w-0">
              <h2 className="text-sm font-semibold text-onsurface truncate" data-testid="viewer-title">
                {title}
              </h2>
              {data?.documentNumber && <p className="text-xs text-onsurface-muted">Số: {data.documentNumber}</p>}
              {data && (
                <span className="inline-block mt-1 text-[10px] px-1.5 py-0.5 rounded-material-full bg-surface-container text-onsurface-muted">
                  {SOURCE_TYPE_LABELS[data.sourceType] ?? data.sourceType}
                </span>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-9 h-9 rounded-material-full hover:bg-surface-container text-onsurface-muted hover:text-onsurface transition-colors duration-200 flex items-center justify-center shrink-0"
            aria-label="Đóng"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {isLoading && (
          <div className="px-5 py-6 flex items-center gap-3 text-sm text-onsurface-muted">
            <span className="w-4 h-4 border-2 border-google-blue border-t-transparent rounded-full animate-spin" />
            Đang tải tài liệu...
          </div>
        )}
        {error && (
          <div className="mx-5 mt-4 px-5 py-6 text-sm text-[#a50e0e] bg-[#fce8e6] rounded-material flex items-center gap-2" data-testid="viewer-error">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="#d93025">
              <path d="M12 2L1 21h22L12 2zm0 14a1 1 0 110 2 1 1 0 010-2zm1-8h-2v6h2V8z" />
            </svg>
            Không thể mở tài liệu này.
          </div>
        )}

        {data && (
          <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
            {(data.issueDate || data.effectiveDate) && (
              <div className="text-[11px] text-onsurface-muted bg-surface-container px-3 py-2.5 rounded-material">
                {data.issueDate && <p>Ngày ban hành: {data.issueDate}</p>}
                {data.effectiveDate && <p>Ngày hiệu lực: {data.effectiveDate}</p>}
              </div>
            )}
            {data.chunks.length === 0 ? (
              <div className="py-4 space-y-3">
                <p className="text-xs text-onsurface-muted text-center">
                  Tài liệu này chưa có cấu trúc điều/khoản được nhận diện.
                </p>
                {citation.content && (
                  <div className="p-3 rounded-material-lg border border-google-blue bg-google-blue/5 text-left">
                    <p className="text-[11px] font-medium text-google-blue mb-1">Đoạn trích dẫn liên quan</p>
                    <p className="text-xs text-onsurface leading-relaxed whitespace-pre-wrap">{citation.content}</p>
                  </div>
                )}
              </div>
            ) : (
              data.chunks.map((chunk) => {
                const label = [
                  chunk.article ? `Điều ${chunk.article}` : null,
                  chunk.clause ? `Khoản ${chunk.clause}` : null,
                  chunk.point ? `Điểm ${chunk.point}` : null,
                ]
                  .filter(Boolean)
                  .join(" · ");
                const isCited = citedChunkId != null && chunk.id === citedChunkId;
                return (
                  <div
                    key={chunk.id}
                    id={`legal-chunk-${chunk.id}`}
                    className={`p-3 rounded-material-lg border text-left ${
                      isCited
                        ? "border-google-blue bg-google-blue/5"
                        : "border-outline bg-surface shadow-material-1"
                    }`}
                    data-cited={isCited || undefined}
                  >
                    <div className="flex items-center justify-between">
                      <p className="text-[11px] font-medium text-google-blue">
                        {label || "Nội dung chung"}
                      </p>
                      {isCited && (
                        <span className="text-[10px] px-2 py-0.5 rounded-material-full bg-google-blue text-white">
                          Trích dẫn
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-onsurface leading-relaxed mt-1 whitespace-pre-wrap">
                      {chunk.content}
                    </p>
                  </div>
                );
              })
            )}
          </div>
        )}
      </aside>
    </div>
  );
}

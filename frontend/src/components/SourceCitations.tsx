import { useState } from "react";
import type { SourceCitation } from "../types";
import { SOURCE_TYPE_LABELS, locationLabel } from "./citationUtils";

function CitationCard({
  source,
  index,
  onViewSource,
}: {
  source: SourceCitation;
  index: number;
  onViewSource?: (s: SourceCitation) => void;
}) {
  const title = source.documentTitle?.trim() || null;
  const location = locationLabel(source);
  const typeLabel = source.sourceType
    ? (SOURCE_TYPE_LABELS[source.sourceType] ?? null)
    : null;

  return (
    <div
      className="p-3 rounded-material-lg bg-surface border border-outline shadow-material-1 text-left animate-slide-up"
      data-testid="citation-card"
      data-source-type={source.sourceType ?? "unknown"}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-xs font-medium text-onsurface truncate" data-testid="citation-title">
            {title ?? "Không xác định tên văn bản"}
          </p>
          {source.documentNumber && (
            <p className="text-[11px] text-onsurface-muted" data-testid="citation-number">
              Số: {source.documentNumber}
            </p>
          )}
          {location && (
            <p className="text-[11px] text-google-blue mt-0.5" data-testid="citation-location">
              {location}
            </p>
          )}
        </div>
        {onViewSource && source.documentId != null && (
          <button
            onClick={() => onViewSource(source)}
            className="shrink-0 text-[11px] px-2.5 py-1.5 rounded-material-full border border-outline bg-surface hover:bg-surface-container text-onsurface-variant transition-colors duration-200"
            data-testid={`view-source-${index}`}
          >
            Xem nguồn
          </button>
        )}
      </div>
      {source.content && (
        <p className="text-xs text-onsurface-muted leading-relaxed italic mt-1.5 line-clamp-3">
          "{source.content}"
        </p>
      )}
      {typeLabel && (
        <span
          className={`inline-block mt-1.5 text-[10px] px-1.5 py-0.5 rounded-material-full ${
            source.sourceType === "OFFICIAL"
              ? "bg-google-green/10 text-google-green"
              : source.sourceType === "FIXTURE"
                ? "bg-[#7b1fa2]/10 text-[#7b1fa2]"
                : "bg-surface-container text-onsurface-muted"
          }`}
          data-testid="citation-source-type"
        >
          {typeLabel}
        </span>
      )}
    </div>
  );
}

/**
 * Structured citation list for an answer (Decision 14).
 *
 * - Renders backend-provided metadata only; missing fields are omitted,
 *   never invented.
 * - Falls back to legacy raw-chunk rendering when no structured sources exist.
 * - Preserves the source order returned by the backend.
 */
export default function SourceCitations({
  sources,
  sourceChunks,
  onViewSource,
}: {
  sources?: SourceCitation[] | null;
  sourceChunks?: string | string[] | null;
  onViewSource?: (s: SourceCitation) => void;
}) {
  const [expanded, setExpanded] = useState(false);

  if (sources && sources.length > 0) {
    return (
      <div className="mt-3" data-testid="source-citations">
        <button
          onClick={() => setExpanded((e) => !e)}
          className="cursor-pointer text-xs text-onsurface-muted hover:text-onsurface transition-colors duration-200 flex items-center gap-1.5 select-none"
          data-testid="citations-toggle"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
            <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
          </svg>
          Nguồn hỗ trợ ({sources.length})
          <span className="text-[10px]">{expanded ? "▲" : "▼"}</span>
        </button>
        {expanded && (
          <div className="mt-2 space-y-2 max-h-64 overflow-y-auto pr-1">
            {sources.map((s, i) => (
              <CitationCard key={i} source={s} index={i} onViewSource={onViewSource} />
            ))}
          </div>
        )}
      </div>
    );
  }

  // Legacy fallback: raw chunk text or array of chunks (older persisted messages).
  const rawChunks: string[] = Array.isArray(sourceChunks)
    ? sourceChunks.map((c) => (typeof c === "string" ? c : JSON.stringify(c)))
    : typeof sourceChunks === "string" && sourceChunks.trim().length > 0
      ? sourceChunks.split("---").map((c) => c.trim()).filter(Boolean)
      : [];

  if (rawChunks.length > 0) {
    return (
      <details className="mt-3 group">
        <summary className="cursor-pointer text-xs text-onsurface-muted hover:text-onsurface transition-colors duration-200 flex items-center gap-1.5 select-none">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
            <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
          </svg>
          Trích dẫn nguồn cơ sở tri thức ({rawChunks.length})
        </summary>
        <div className="mt-2 space-y-2 max-h-48 overflow-y-auto pr-1">
          {rawChunks.map((chunk, i) => {
            const match = chunk.trim().match(/^\[(.*?)\] (.*)$/s);
            const textContent = match ? match[2] : chunk;
            return (
              <div
                key={i}
                className="p-2.5 rounded-material-lg bg-surface border border-outline text-left shadow-material-1"
              >
                <p className="text-xs text-onsurface-muted leading-relaxed italic">
                  "{textContent.trim()}"
                </p>
              </div>
            );
          })}
        </div>
      </details>
    );
  }

  return null;
}

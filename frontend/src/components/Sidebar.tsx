import { useState } from "react";
import type { Document } from "../types";
import SearchInput from "./SearchInput";
import SessionList from "./SessionList";
import DocumentMenu from "./DocumentMenu";

interface SidebarProps {
  documents: Document[];
  selectedDoc: Document | null;
  onSelectDoc: (doc: Document | null) => void;
  onNewChat: () => void;
  onUploadClick: () => void;
  isOpen: boolean;
  onClose: () => void;
  activeSessionId: string;
  onSelectSession: (sessionId: string) => void;
  onRenameDoc: (doc: Document) => void;
  onDeleteDoc: (doc: Document) => void;
  onViewVersions: (doc: Document) => void;
  onDeleteBatchDocs?: (ids: number[]) => void;
}

export default function Sidebar({
  documents,
  selectedDoc,
  onSelectDoc,
  onNewChat,
  onUploadClick,
  isOpen,
  onClose,
  activeSessionId,
  onSelectSession,
  onRenameDoc,
  onDeleteDoc,
  onViewVersions,
  onDeleteBatchDocs,
}: SidebarProps) {
  const [isMultiSelect, setIsMultiSelect] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());

  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const handleSelectAll = () => {
    if (selectedIds.size === documents.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(documents.map((d) => d.id)));
    }
  };

  const handleBatchDelete = () => {
    if (selectedIds.size > 0 && onDeleteBatchDocs) {
      onDeleteBatchDocs(Array.from(selectedIds));
    }
  };

  return (
    <>
      {/* Mobile overlay */}
      {isOpen && (
        <div
          data-testid="mobile-overlay"
          className="fixed inset-0 bg-black/30 z-40 lg:hidden"
          onClick={onClose}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`
          fixed lg:relative z-50 lg:z-auto
          w-sidebar h-full bg-surface border-r border-outline
          flex flex-col shrink-0
          transition-transform duration-300 ease-material
          ${isOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"}
        `}
      >
        {/* Header: New Chat */}
        <div className="p-3 border-b border-outline">
          <button
            onClick={() => { onNewChat(); onClose(); }}
            className="w-full flex items-center gap-3 px-4 py-3 rounded-material-full border border-outline hover:bg-surface-container hover:shadow-material-btn transition-all duration-200 cursor-pointer"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="text-google-blue">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
            <span className="text-[14px] text-onsurface font-medium">Cuộc trò chuyện mới</span>
          </button>
        </div>

        {/* Scrollable Container for Search, Documents, and Sessions */}
        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {/* Search */}
          <SearchInput onSelectDoc={(doc) => { onSelectDoc(doc as Document); onClose(); }} />

          {/* Documents section */}
          <div className="space-y-1">
            <div className="flex items-center justify-between px-3 py-2">
              <p className="text-[11px] text-onsurface-muted font-medium uppercase tracking-wider">
                Tài liệu ({documents.length})
              </p>
              {documents.length > 0 && (
                <button
                  onClick={() => {
                    setIsMultiSelect(!isMultiSelect);
                    if (isMultiSelect) setSelectedIds(new Set());
                  }}
                  className="text-[11px] font-medium text-google-blue hover:underline cursor-pointer"
                  type="button"
                >
                  {isMultiSelect ? "Hủy chọn" : "Chọn nhiều"}
                </button>
              )}
            </div>

            {/* Multi-select action bar */}
            {isMultiSelect && documents.length > 0 && (
              <div className="p-2 mb-2 bg-surface-container rounded-material border border-outline flex flex-col gap-2 animate-fade-in">
                <div className="flex items-center justify-between">
                  <label className="flex items-center gap-2 text-[12px] font-medium text-onsurface cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={selectedIds.size === documents.length && documents.length > 0}
                      onChange={handleSelectAll}
                      className="w-4 h-4 rounded text-google-blue cursor-pointer"
                      aria-label="Chọn tất cả tài liệu"
                    />
                    Chọn tất cả ({documents.length})
                  </label>
                  <span className="text-[11px] text-onsurface-muted font-semibold">
                    Đã chọn: {selectedIds.size}
                  </span>
                </div>
                {selectedIds.size > 0 && (
                  <button
                    onClick={handleBatchDelete}
                    className="w-full flex items-center justify-center gap-2 py-1.5 px-3 bg-red-600 hover:bg-red-700 text-white rounded-material text-[12px] font-medium transition-colors shadow-sm cursor-pointer"
                    type="button"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="3 6 5 6 21 6" />
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                    </svg>
                    Xóa {selectedIds.size} tài liệu đã chọn
                  </button>
                )}
              </div>
            )}

            {/* Upload button */}
            <button
              onClick={onUploadClick}
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-material hover:bg-surface-container transition-colors duration-200 text-left cursor-pointer"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="text-google-blue">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
              <span className="text-[13px] text-onsurface-variant">Tải lên tài liệu</span>
            </button>

            {/* Document list */}
            {(!documents || !Array.isArray(documents) || documents.length === 0) ? (
              <p className="px-3 py-4 text-[12px] text-onsurface-muted text-center">
                Chưa có tài liệu. Tải lên để bắt đầu.
              </p>
            ) : (
              <div className="space-y-0.5">
                {(Array.isArray(documents) ? documents : []).map((doc) => {
                  const isChecked = selectedIds.has(doc.id);
                  return (
                    <div
                      key={doc.id}
                      role="button"
                      tabIndex={0}
                      onClick={() => {
                        if (isMultiSelect) {
                          toggleSelect(doc.id);
                        } else {
                          onSelectDoc(doc);
                          onClose();
                        }
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          if (isMultiSelect) {
                            toggleSelect(doc.id);
                          } else {
                            onSelectDoc(doc);
                            onClose();
                          }
                        }
                      }}
                      className={`
                        w-full flex items-center gap-2.5 px-3 py-2 rounded-material text-left transition-colors duration-200 cursor-pointer
                        ${selectedDoc?.id === doc.id && !isMultiSelect
                          ? "bg-google-blue/10 text-google-blue"
                          : isChecked
                          ? "bg-red-50 dark:bg-red-950/20 text-onsurface"
                          : "hover:bg-surface-container text-onsurface"
                        }
                      `}
                    >
                      {isMultiSelect ? (
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={() => toggleSelect(doc.id)}
                          onClick={(e) => e.stopPropagation()}
                          className="w-4 h-4 rounded text-google-blue cursor-pointer shrink-0"
                          aria-label={`Chọn tài liệu ${doc.title || doc.fileName}`}
                        />
                      ) : (
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className={selectedDoc?.id === doc.id ? "text-google-blue shrink-0" : "text-onsurface-muted shrink-0"}>
                          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                          <polyline points="14 2 14 8 20 8" />
                        </svg>
                      )}
                      <div className="min-w-0 flex-1">
                        <p className="text-[13px] truncate font-medium">
                          {doc.title || doc.fileName}
                        </p>
                        <p className="text-[11px] text-onsurface-muted truncate">
                          {doc.documentNumber ? `Số: ${doc.documentNumber}` : (doc.fileType || "PDF")} &bull; {doc.chunkCount || 24} chunks
                        </p>
                      </div>
                      {!isMultiSelect && (
                        <DocumentMenu
                          document={doc}
                          onRename={() => onRenameDoc(doc)}
                          onDelete={() => onDeleteDoc(doc)}
                          onViewHistory={() => onViewVersions(doc)}
                        />
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Sessions */}
          <SessionList
            activeSessionId={activeSessionId}
            onSelectSession={(id) => { onSelectSession(id); onClose(); }}
            onResetSession={onNewChat}
          />
        </div>

        {/* Footer */}
        <div className="p-3 border-t border-outline">
          <div className="px-2 text-[11px] text-onsurface-muted text-center leading-4">
            Smart Doc &bull; Enterprise CRAG
          </div>
        </div>
      </aside>
    </>
  );
}

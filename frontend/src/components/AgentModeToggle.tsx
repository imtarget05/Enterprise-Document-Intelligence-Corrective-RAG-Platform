interface AgentModeToggleProps {
  agentMode: boolean;
  onToggle: (mode: boolean) => void;
}

export default function AgentModeToggle({ agentMode, onToggle }: AgentModeToggleProps) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <button
        onClick={() => onToggle(false)}
        className={`px-3 py-1 rounded-material-full text-[12px] font-medium transition-all duration-200 ${
          !agentMode
            ? "bg-google-blue text-white shadow-material-btn"
            : "bg-surface-container text-onsurface-variant hover:bg-outline"
        }`}
      >
        RAG
      </button>
      <div className="relative group">
        <button
          onClick={() => onToggle(true)}
          className={`px-3 py-1 rounded-material-full text-[12px] font-medium transition-all duration-200 flex items-center gap-1.5 ${
            agentMode
              ? "bg-google-blue text-white shadow-material-btn"
              : "bg-surface-container text-onsurface-variant hover:bg-outline"
          }`}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M12 1v4m0 14v4M4.22 4.22l2.83 2.83m9.9 9.9l2.83 2.83M1 12h4m14 0h4M4.22 19.78l2.83-2.83m9.9-9.9l2.83-2.83" />
          </svg>
          Agent
          <span className="text-[9px] bg-google-yellow text-black px-1.5 py-0.5 rounded-material-full font-bold">
            BETA
          </span>
        </button>
        {/* Tooltip */}
        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-3 py-2 bg-onsurface text-white text-[11px] rounded-material shadow-material-2 opacity-0 group-hover:opacity-100 transition pointer-events-none whitespace-nowrap z-50">
          Agent BETA đang thử nghiệm; khi agent không sẵn sàng, hệ thống chuyển về RAG.
          <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-onsurface" />
        </div>
      </div>
      {agentMode && (
        <span className="text-[11px] text-google-blue font-medium ml-1">
          Đã chọn Agent BETA (có thể chuyển về RAG)
        </span>
      )}
    </div>
  );
}

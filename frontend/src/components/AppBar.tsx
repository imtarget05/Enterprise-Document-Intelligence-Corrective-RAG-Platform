import { useAuth } from "../context/AuthContext";
import { useApprovalsQueue } from "../hooks/useApprovals";

interface AppBarProps {
  onMenuClick: () => void;
  username?: string | null;
  onLogout: () => void;
  currentView?: "chat" | "admin";
  onViewChange?: (view: "chat" | "admin") => void;
}

export default function AppBar({ onMenuClick, username, onLogout, currentView = "chat", onViewChange }: AppBarProps) {
  const { role, isAdmin, login, token } = useAuth();
  const { data: approvalsData } = useApprovalsQueue(token, Boolean(token));
  const pendingCount = approvalsData?.pending?.length ?? approvalsData?.count ?? 0;
  const initials = username ? username.slice(0, 2).toUpperCase() : "U";

  const handleSwitchView = (target: "chat" | "admin") => {
    if (onViewChange) {
      onViewChange(target);
    }
    const bridge = (window as unknown as { __appView?: ["chat" | "admin", (v: "chat" | "admin") => void] }).__appView;
    if (bridge && bridge[1]) {
      bridge[1](target);
    }
  };

  return (
    <header className="h-appbar bg-surface border-b border-outline flex items-center justify-between px-4 shrink-0">
      {/* Left: menu + logo */}
      <div className="flex items-center gap-3">
        <button
          onClick={onMenuClick}
          className="lg:hidden w-10 h-10 rounded-material-full hover:bg-surface-container flex items-center justify-center transition-colors duration-200"
          aria-label="Mở menu"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="text-onsurface-variant">
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>

        {/* Logo */}
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 bg-google-blue rounded-material flex items-center justify-center">
            <svg width="16" height="16" viewBox="0 0 24 24">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" fill="white" opacity="0.3" />
              <polyline points="14 2 14 8 20 8" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" />
              <line x1="16" y1="13" x2="8" y2="13" stroke="white" strokeWidth="2" strokeLinecap="round" />
              <line x1="16" y1="17" x2="8" y2="17" stroke="white" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </div>
          <h1 className="text-[18px] text-onsurface font-medium tracking-tight hidden sm:block">
            Smart Document AI
          </h1>
        </div>
      </div>

      {/* Center: Interactive Mode Switcher */}
      <div className="flex items-center gap-1 bg-surface-container/70 p-1 rounded-material-full border border-outline">
        <button
          type="button"
          onClick={() => handleSwitchView("chat")}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-material-full text-[13px] font-medium transition cursor-pointer ${
            currentView !== "admin"
              ? "bg-google-blue text-white shadow-xs"
              : "text-onsurface-variant hover:text-onsurface hover:bg-surface"
          }`}
        >
          <span>💬</span>
          <span className="hidden md:inline">Trợ lý Chatbot RAG</span>
          <span className="md:hidden">Chat</span>
        </button>

        <button
          type="button"
          onClick={() => handleSwitchView("admin")}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-material-full text-[13px] font-medium transition cursor-pointer ${
            currentView === "admin"
              ? "bg-google-blue text-white shadow-xs"
              : "text-onsurface-variant hover:text-onsurface hover:bg-surface"
          }`}
        >
          <span>🛡️</span>
          <span className="hidden md:inline">Quản Trị &amp; HITL Queue</span>
          <span className="md:hidden">Quản Trị</span>
          {pendingCount > 0 && (
            <span className="ml-1 px-1.5 py-0.2 bg-amber-500 text-white rounded-full text-[10px] font-bold">
              {pendingCount}
            </span>
          )}
        </button>
      </div>

      {/* Right: user menu */}
      <div className="relative group">
        <button
          className="w-9 h-9 rounded-material-full bg-google-blue text-white text-[13px] font-medium flex items-center justify-center hover:shadow-material-btn transition-shadow duration-200 cursor-pointer"
          aria-label="Menu người dùng"
        >
          {initials}
        </button>

        {/* Dropdown */}
        <div className="absolute right-0 top-full mt-2 w-64 bg-surface border border-outline rounded-material-lg shadow-material-3 opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 z-50 overflow-hidden">
          <div className="px-4 py-3 border-b border-outline">
            <p className="text-[13px] text-onsurface font-medium truncate">{username || "admin@smartdoc.ai"}</p>
            <div className="mt-1 flex items-center gap-1.5">
              <span className={`inline-block text-[10px] font-bold px-2 py-0.5 rounded ${
                isAdmin ? "bg-emerald-100 text-emerald-800" : "bg-slate-200 text-slate-800"
              }`}>
                {role || (isAdmin ? "ROLE_ADMIN" : "ROLE_USER")}
              </span>
              <span className="text-[11px] text-onsurface-muted">
                {isAdmin ? "Toàn quyền" : "Quyền người dùng"}
              </span>
            </div>
          </div>

          {/* IAM Role Switcher */}
          <div className="p-3 bg-slate-50 border-b border-outline">
            <p className="text-[11px] font-semibold text-slate-600 mb-1.5 flex items-center justify-between">
              <span>Phân quyền IAM (RBAC)</span>
              <span className="text-[10px] text-google-blue font-normal">Thử nghiệm</span>
            </p>
            <div className="grid grid-cols-2 gap-1.5">
              <button
                type="button"
                onClick={() => login(token, "admin@smartdoc.ai", "ROLE_ADMIN")}
                className={`py-1 px-2 rounded text-xs font-semibold transition cursor-pointer ${
                  isAdmin ? "bg-google-blue text-white shadow-xs" : "bg-white border border-slate-200 text-slate-700 hover:bg-slate-100"
                }`}
              >
                👑 Admin
              </button>
              <button
                type="button"
                onClick={() => {
                  login(token, "nhanvien@smartdoc.ai", "ROLE_USER");
                  handleSwitchView("chat");
                }}
                className={`py-1 px-2 rounded text-xs font-semibold transition cursor-pointer ${
                  !isAdmin ? "bg-slate-800 text-white shadow-xs" : "bg-white border border-slate-200 text-slate-700 hover:bg-slate-100"
                }`}
              >
                👤 User
              </button>
            </div>
          </div>

          <button
            onClick={() => handleSwitchView(currentView === "admin" ? "chat" : "admin")}
            className="w-full text-left px-4 py-2.5 text-[13px] text-google-blue hover:bg-surface-container transition-colors duration-200 flex items-center gap-2 cursor-pointer"
          >
            <span>{currentView === "admin" ? "💬 Mở Chatbot RAG" : "🛡️ Mở Quản trị HITL"}</span>
          </button>

          <button
            onClick={onLogout}
            className="w-full text-left px-4 py-2.5 text-[13px] text-rose-600 hover:bg-rose-50 transition-colors duration-200 flex items-center gap-2 cursor-pointer border-t border-outline/50"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
              <polyline points="16 17 21 12 16 7" />
              <line x1="21" y1="12" x2="9" y2="12" />
            </svg>
            Đăng xuất
          </button>
        </div>
      </div>
    </header>
  );
}

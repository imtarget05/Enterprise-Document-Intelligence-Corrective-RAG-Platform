interface AdminSidebarProps {
  activeTab: string;
  onTabChange: (tab: string) => void;
  /** False for ENGINEER (sees only the approvals queue, not admin tabs). */
  canAdmin?: boolean;
}

const TABS = [
  { id: "overview", label: "Tổng quan", icon: "📊", adminOnly: true },
  { id: "approvals", label: "Phê duyệt", icon: "⏸", adminOnly: false },
  { id: "audit", label: "Audit Logs", icon: "📋", adminOnly: true },
];

export default function AdminSidebar({ activeTab, onTabChange, canAdmin = true }: AdminSidebarProps) {
  const visibleTabs = TABS.filter((tab) => canAdmin || !tab.adminOnly);
  return (
    <aside className="w-56 h-full bg-surface border-r border-outline flex flex-col shrink-0">
      <div className="p-4 border-b border-outline">
        <h2 className="text-[14px] font-semibold text-onsurface">Admin Dashboard</h2>
        <p className="text-[11px] text-onsurface-muted mt-0.5">Quản trị hệ thống</p>
      </div>
      <div className="p-2 border-b border-outline">
        <button
          onClick={() => {
            const bridge = (window as unknown as { __appView?: ["chat" | "admin", (v: "chat" | "admin") => void] }).__appView;
            if (bridge) bridge[1]("chat");
          }}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-material text-[13px] text-google-blue hover:bg-google-blue/10 transition font-medium"
        >
          <span>←</span>
          <span>Quay lại Trò chuyện</span>
        </button>
      </div>
      <nav className="flex-1 p-2 space-y-0.5">
        {visibleTabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
            className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-material text-[13px] text-left transition ${
              activeTab === tab.id
                ? "bg-google-blue/10 text-google-blue font-medium"
                : "text-onsurface-variant hover:bg-surface-container"
            }`}
          >
            <span>{tab.icon}</span>
            {tab.label}
          </button>
        ))}
      </nav>
    </aside>
  );
}

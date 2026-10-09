import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../context/AuthContext";
import { API_BASE_URL } from "../context/apiConfig";
import { useAuditLogs } from "../hooks/useAuditLogs";
import AppBar from "../components/AppBar";
import AdminSidebar from "../components/AdminSidebar";
import AuditLogTable from "../components/AuditLogTable";
import ApprovalsTable from "../components/ApprovalsTable";

export default function AdminPage() {
  const { isAdmin, isEngineer, token, username, logout } = useAuth();
  // ENGINEER may only touch the HITL approvals queue — never admin tabs.
  const canApprove = isAdmin || isEngineer;
  const [activeTab, setActiveTab] = useState(isAdmin ? "overview" : "approvals");

  if (!canApprove) {
    return (
      <div className="flex-1 flex items-center justify-center bg-surface-dim">
        <div className="text-center">
          <span className="text-4xl">🔒</span>
          <p className="text-[14px] text-onsurface-muted mt-2">Bạn không có quyền truy cập trang quản trị.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-screen bg-surface-dim">
      <AppBar onMenuClick={() => {}} username={username} onLogout={logout} />
      <div className="flex flex-1 overflow-hidden">
        <AdminSidebar activeTab={activeTab} onTabChange={setActiveTab} canAdmin={isAdmin} />
        <main className="flex-1 flex flex-col overflow-hidden bg-surface-dim">
          {activeTab === "overview" && isAdmin && <AdminOverview />}
          {activeTab === "approvals" && <ApprovalsTable token={token} />}
          {activeTab === "audit" && isAdmin && <AuditLogTable />}
        </main>
      </div>
    </div>
  );
}

function AdminOverview() {
  const { token, username } = useAuth();
  const { data: documents = [] } = useQuery<Array<{ id: number; title?: string }>>({
    queryKey: ["documents", username, token],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/documents`, {
        credentials: "include",
        headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      });
      if (!res.ok) return [];
      return res.json();
    },
    enabled: !!username || !!token,
  });

  const { data: auditData } = useAuditLogs({ page: 0, size: 1 });

  return (
    <div className="p-6 overflow-y-auto space-y-6">
      <div>
        <h1 className="text-[20px] text-onsurface font-medium">Tổng quan hệ thống Smart Document AI</h1>
        <p className="text-[13px] text-onsurface-muted mt-1">
          Hệ thống lưu trữ cơ sở tri thức pháp luật, quy chuẩn an toàn thông tin và giám sát tuân thủ cho doanh nghiệp.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <StatCard label="Văn bản pháp luật & quy chế" value={String(documents.length)} icon="📄" />
        <StatCard label="Tài khoản truy cập" value={username ?? "—"} icon="👤" />
        <StatCard label="Nhật ký Audit Trail" value={String(auditData?.totalElements ?? 0)} icon="📋" />
      </div>

      <div className="bg-surface border border-outline rounded-material-lg p-5 shadow-material-1">
        <h2 className="text-[15px] font-medium text-onsurface mb-3">Kiến trúc hạ tầng & Dữ liệu thực tế</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-[13px]">
          <div className="space-y-2">
            <p className="text-onsurface-variant"><strong className="text-onsurface">Cơ sở dữ liệu:</strong> Neon Serverless PostgreSQL (Singapore Region)</p>
            <p className="text-onsurface-variant"><strong className="text-onsurface">Bảo vệ lưu trữ:</strong> Xử lý bộ nhớ luồng trực tiếp (Zero Disk Footprint)</p>
            <p className="text-onsurface-variant"><strong className="text-onsurface">Cơ chế RAG:</strong> CRAG (Corrective RAG) + Phân tích cấu trúc pháp lý (Điều/Khoản/Điểm)</p>
          </div>
          <div className="space-y-2">
            <p className="text-onsurface-variant"><strong className="text-onsurface">Định dạng hỗ trợ:</strong> PDF, DOCX, DOC, DOCS, TXT</p>
            <p className="text-onsurface-variant"><strong className="text-onsurface">Bảo mật & Kiểm tra:</strong> Prompt Injection Shield + Nhật ký kiểm toán đầy đủ</p>
            <p className="text-onsurface-variant"><strong className="text-onsurface">Xác thực:</strong> JWT + SSO/OIDC (Keycloak), CSRF double-submit cookie</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, icon }: { label: string; value: string; icon: string }) {
  return (
    <div className="bg-surface border border-outline rounded-material-lg p-4 shadow-material-1">
      <div className="flex items-center gap-3">
        <span className="text-[24px]">{icon}</span>
        <div>
          <p className="text-[24px] font-normal text-onsurface">{value}</p>
          <p className="text-[12px] text-onsurface-muted">{label}</p>
        </div>
      </div>
    </div>
  );
}

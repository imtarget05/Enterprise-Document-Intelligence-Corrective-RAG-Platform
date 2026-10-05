import { useState, useMemo, useRef, useEffect, useCallback } from "react";
import { useAuth } from "../context/AuthContext";
import { API_BASE_URL } from "../context/apiConfig";
import { ensureCsrfHeaders } from "../csrf";

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: { client_id: string; callback: (resp: { credential: string }) => void }) => void;
          renderButton: (el: HTMLElement, options: Record<string, unknown>) => void;
          prompt: () => void;
        };
      };
    };
  }
}

let GOOGLE_CLIENT_ID = "";
void fetch(`${API_BASE_URL}/auth/google-client-id`)
  .then((r) => (r.ok ? r.json() : null))
  .then((d) => { if (d?.clientId) GOOGLE_CLIENT_ID = d.clientId; })
  .catch(() => {});
function DocIcon({ size = 20, className = "" }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" className={className}>
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" fill="currentColor" opacity="0.2" />
      <polyline points="14 2 14 8 20 8" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <line x1="16" y1="13" x2="8" y2="13" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <line x1="16" y1="17" x2="8" y2="17" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <polyline points="10 9 9 9 8 9" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

function GoogleLogo() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24s.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  );
}

function ErrorIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="#d93025">
      <path d="M12 2L1 21h22L12 2zm0 14a1 1 0 110 2 1 1 0 010-2zm1-8h-2v6h2V8z" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="#34a853">
      <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z" />
    </svg>
  );
}

function PasswordStrength({ password }: { password: string }) {
  const strength = useMemo(() => {
    if (!password) return { level: 0, label: "", color: "" };
    let score = 0;
    if (password.length >= 12) score++;
    if (password.length >= 16) score++;
    if (/[A-Z]/.test(password)) score++;
    if (/[0-9]/.test(password)) score++;
    if (/[^A-Za-z0-9]/.test(password)) score++;
    if (score <= 2) return { level: 1, label: "Yếu", color: "#d93025" };
    if (score <= 3) return { level: 2, label: "Trung bình", color: "#fbbc05" };
    if (score <= 4) return { level: 3, label: "Mạnh", color: "#34a853" };
    return { level: 4, label: "Rất mạnh", color: "#1a73e8" };
  }, [password]);
  if (!password) return null;
  return (
    <div className="mt-1.5 space-y-1">
      <div className="flex gap-1">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-1 flex-1 rounded-full transition-all duration-300" style={{ backgroundColor: i <= strength.level ? strength.color : "#e8eaed" }} />
        ))}
      </div>
      <p className="text-[11px]" style={{ color: strength.color }}>Độ mạnh: {strength.label}</p>
    </div>
  );
}

export default function LoginPage() {
  const { login } = useAuth();
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [authUsername, setAuthUsername] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showReset, setShowReset] = useState(false);
  const [resetEmail, setResetEmail] = useState("");
  const [authError, setAuthError] = useState("");
  const [authLoading, setAuthLoading] = useState(false);
  const [resetSent, setResetSent] = useState(false);

  const handleAuthSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!authUsername.trim() || !authPassword.trim()) {
      setAuthError("Vui lòng điền đầy đủ thông tin");
      return;
    }
    if (authMode === "register" && authPassword !== confirmPassword) {
      setAuthError("Mật khẩu xác nhận không khớp");
      return;
    }
    if (authMode === "register" && authPassword.length < 12) {
      setAuthError("Mật khẩu phải ít nhất 12 ký tự");
      return;
    }
    setAuthError("");
    setAuthLoading(true);
    try {
      const endpoint = authMode === "login" ? "/auth/login" : "/auth/register";
      const payload: Record<string, string> = { username: authUsername, password: authPassword };
      if (authMode === "register") {
        payload.email = authUsername.includes("@") ? authUsername : `${authUsername}@example.com`;
      }
      const response = await fetch(`${API_BASE_URL}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await ensureCsrfHeaders()) },
        credentials: "include",
        body: JSON.stringify(payload),
      });
      const text = await response.text();
      let data: Record<string, string> = {};
      try { data = text ? JSON.parse(text) : {}; } catch { data = { error: text }; }
      if (!response.ok) throw new Error(data.error || data.message || text || "Xác thực thất bại");
      login(data.token, data.username, data.role);
    } catch (err: unknown) {
      if (err instanceof TypeError) {
        setAuthError("Không thể kết nối máy chủ. Máy chủ có thể đang khởi động — vui lòng thử lại sau vài giây.");
      } else {
        setAuthError(err instanceof Error ? err.message : "Đã có lỗi xảy ra");
      }
    } finally {
      setAuthLoading(false);
    }
  };

  const [googleModalOpen, setGoogleModalOpen] = useState(false);
  const googleBtnRef = useRef<HTMLDivElement | null>(null);

  const postGoogleCredential = useCallback(
    async (credential: string): Promise<Response> => {
      const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
      let res: Response | null = null;
      for (let attempt = 0; attempt < 3; attempt++) {
        if (attempt > 0) await sleep(4000);
        try {
          res = await fetch(`${API_BASE_URL}/auth/google`, {
            method: "POST",
            credentials: "include",
            headers: { "Content-Type": "application/json", ...(await ensureCsrfHeaders()) },
            body: JSON.stringify({ credential }),
          });
          break;
        } catch {
          continue;
        }
      }
      if (!res) {
        throw new Error("Không thể kết nối máy chủ. Máy chủ có thể đang khởi động — vui lòng thử lại sau vài giây.");
      }
      return res;
    },
    [],
  );

  const handleGoogleCredential = useCallback(
    async (credential: string) => {
      setAuthLoading(true);
      setAuthError("");
      try {
        const res = await postGoogleCredential(credential);
        const text = await res.text();
        let data: Record<string, string> = {};
        try { data = text ? JSON.parse(text) : {}; } catch { data = { error: text }; }
        if (!res.ok) throw new Error(data.error || data.message || text || "Đăng nhập Google thất bại");
        setGoogleModalOpen(false);
        login(data.token, data.username, data.role);
      } catch (err: unknown) {
        if (err instanceof TypeError) {
          setAuthError("Không thể kết nối máy chủ. Máy chủ có thể đang khởi động — vui lòng thử lại sau vài giây.");
        } else {
          setAuthError(err instanceof Error ? err.message : "Đăng nhập Google thất bại");
        }
      } finally {
        setAuthLoading(false);
      }
    },
    [login, postGoogleCredential],
  );

  // Google Identity Services One Tap auto-login: if the browser still has the
  // user's Google session, prompt for it automatically so they don't have to
  // click through the login form again.
  const googleAutoAttempted = useRef(false);
  useEffect(() => {
    if (!GOOGLE_CLIENT_ID || googleAutoAttempted.current) return;
    const g = window.google?.accounts?.id;
    if (!g) return;
    googleAutoAttempted.current = true;
    try {
      g.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: (resp) => {
          if (resp?.credential) void handleGoogleCredential(resp.credential);
        },
      });
      g.prompt();
    } catch {
      /* prompt unavailable — user can still use the button */
    }
  }, [handleGoogleCredential]);

  const renderGoogleButton = useCallback(() => {
    const el = googleBtnRef.current;
    if (!el || !window.google?.accounts?.id) return;
    window.google.accounts.id.initialize({
      client_id: GOOGLE_CLIENT_ID,
      callback: (resp) => { void handleGoogleCredential(resp.credential); },
    });
    window.google.accounts.id.renderButton(el, { theme: "outline", size: "large", width: 320, text: "continue_with", locale: "vi" });
  }, [handleGoogleCredential]);

  const handleGoogleLogin = async () => {
    if (!GOOGLE_CLIENT_ID) {
      try {
        const r = await fetch(`${API_BASE_URL}/auth/google-client-id`);
        if (r.ok) {
          const d = await r.json();
          if (d?.clientId) GOOGLE_CLIENT_ID = d.clientId;
        }
      } catch { /* modal shows unconfigured state */ }
    }
    setGoogleModalOpen(true);
  };

  useEffect(() => {
    if (!googleModalOpen) return;
    let cancelled = false;
    const init = () => { if (!cancelled) renderGoogleButton(); };
    if (GOOGLE_CLIENT_ID) {
      if (window.google?.accounts?.id) init();
      else {
        const s = document.createElement("script");
        s.src = "https://accounts.google.com/gsi/client";
        s.async = true; s.defer = true;
        s.onload = init;
        document.head.appendChild(s);
      }
    }
    return () => { cancelled = true; };
  }, [googleModalOpen, renderGoogleButton]);

  const [resetToken, setResetToken] = useState<string | null>(() => {
    if (typeof window !== "undefined") {
      return new URLSearchParams(window.location.search).get("token");
    }
    return null;
  });
  const [newResetPassword, setNewResetPassword] = useState("");
  const [confirmResetPassword, setConfirmResetPassword] = useState("");
  const [resetSuccess, setResetSuccess] = useState(false);

  const handleReset = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!resetEmail.trim()) { setAuthError("Vui lòng nhập email"); return; }
    setAuthLoading(true); setAuthError("");
    try {
      const res = await fetch(`${API_BASE_URL}/auth/reset-password/request`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await ensureCsrfHeaders()) },
        credentials: "include",
        body: JSON.stringify({ email: resetEmail }),
      });
      const t = await res.text();
      if (!res.ok) throw new Error(t || "Gửi email thất bại");
      setResetSent(true);
    } catch (err: unknown) {
      setAuthError(err instanceof Error ? err.message : "Gửi thất bại");
    } finally { setAuthLoading(false); }
  };

  const handleConfirmReset = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newResetPassword || !confirmResetPassword) {
      setAuthError("Vui lòng nhập đầy đủ mật khẩu mới");
      return;
    }
    if (newResetPassword !== confirmResetPassword) {
      setAuthError("Mật khẩu xác nhận không khớp");
      return;
    }
    if (newResetPassword.length < 12) {
      setAuthError("Mật khẩu phải có ít nhất 12 ký tự");
      return;
    }
    setAuthLoading(true);
    setAuthError("");
    try {
      const res = await fetch(`${API_BASE_URL}/auth/reset-password/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await ensureCsrfHeaders()) },
        credentials: "include",
        body: JSON.stringify({ token: resetToken, newPassword: newResetPassword }),
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || "Đặt lại mật khẩu thất bại");
      }
      setResetSuccess(true);
      window.history.replaceState({}, document.title, window.location.pathname);
    } catch (err: unknown) {
      setAuthError(err instanceof Error ? err.message : "Đặt lại mật khẩu thất bại");
    } finally {
      setAuthLoading(false);
    }
  };

  const switchMode = () => {
    setAuthMode(authMode === "login" ? "register" : "login");
    setAuthError("");
    setConfirmPassword("");
  };

  if (resetToken) {
    return (
      <div className="min-h-screen bg-surface-dim flex">
        <div className="hidden lg:flex w-[52%] bg-gradient-to-br from-google-blue via-google-blueLight to-google-blueDark p-12 text-white flex-col justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 bg-white/20 rounded-material flex items-center justify-center">
              <DocIcon size={20} className="text-white" />
            </div>
            <span className="text-[15px] font-medium">Smart Document</span>
          </div>
          <div className="my-auto">
            <h2 className="text-[40px] leading-[48px] font-normal tracking-tight">Tạo mật khẩu mới</h2>
            <p className="text-[16px] text-white/80 mt-4 max-w-[360px] leading-6">Nhập mật khẩu mới an toàn cho tài khoản của bạn</p>
          </div>
          <div className="text-white/60 text-[12px]">&copy; 2026 Smart Document Chatbot &bull; Enterprise CRAG</div>
        </div>
        <div className="flex-1 flex items-center justify-center p-6">
          <div className="w-full max-w-[448px]">
            <h1 className="text-[24px] leading-8 text-onsurface font-normal">Đặt lại mật khẩu mới</h1>
            <p className="text-[14px] text-onsurface-muted mt-1">Xác thực bằng mã token bảo mật</p>
            {resetSuccess ? (
              <div className="mt-6 space-y-4">
                <div className="p-4 bg-[#e6f4ea] border border-google-green rounded-material text-google-green text-[14px] flex items-center gap-2">
                  <CheckIcon />
                  <span>Đặt lại mật khẩu thành công!</span>
                </div>
                <button
                  type="button"
                  onClick={() => { setResetToken(null); setShowReset(false); }}
                  className="w-full bg-google-blue hover:bg-google-blueDark text-white py-2.5 rounded-material-full text-[14px] font-medium"
                >
                  Đăng nhập ngay
                </button>
              </div>
            ) : (
              <form onSubmit={handleConfirmReset} className="mt-6 space-y-4">
                <div className="relative">
                  <input
                    type="password"
                    value={newResetPassword}
                    onChange={(e) => setNewResetPassword(e.target.value)}
                    placeholder="Mật khẩu mới"
                    className="peer w-full px-3.5 py-3.5 border border-outline rounded-material text-[16px] placeholder-transparent focus:outline-none focus:border-google-blue focus:ring-1 focus:ring-google-blue"
                  />
                  <label className="absolute left-3 -top-2.5 bg-white px-1 text-[12px] text-google-blue peer-placeholder-shown:top-3.5 peer-placeholder-shown:text-[16px] peer-placeholder-shown:text-onsurface-muted peer-focus:-top-2.5 peer-focus:text-[12px] peer-focus:text-google-blue transition-all duration-200">
                    Mật khẩu mới (tối thiểu 6 ký tự)
                  </label>
                </div>
                <div className="relative">
                  <input
                    type="password"
                    value={confirmResetPassword}
                    onChange={(e) => setConfirmResetPassword(e.target.value)}
                    placeholder="Xác nhận mật khẩu mới"
                    className="peer w-full px-3.5 py-3.5 border border-outline rounded-material text-[16px] placeholder-transparent focus:outline-none focus:border-google-blue focus:ring-1 focus:ring-google-blue"
                  />
                  <label className="absolute left-3 -top-2.5 bg-white px-1 text-[12px] text-google-blue peer-placeholder-shown:top-3.5 peer-placeholder-shown:text-[16px] peer-placeholder-shown:text-onsurface-muted peer-focus:-top-2.5 peer-focus:text-[12px] peer-focus:text-google-blue transition-all duration-200">
                    Xác nhận mật khẩu mới
                  </label>
                </div>
                {authError && (
                  <div className="flex gap-2 items-start bg-[#fce8e6] border border-[#f5c6cb] text-[#a50e0e] text-[13px] px-3 py-2.5 rounded-material">
                    <ErrorIcon />
                    <span>{authError}</span>
                  </div>
                )}
                <div className="flex items-center justify-between pt-2">
                  <button
                    type="button"
                    onClick={() => { setResetToken(null); setShowReset(false); }}
                    className="text-google-blue text-[14px] font-medium px-3 py-2 hover:bg-surface-container rounded-material-full"
                  >
                    Hủy bỏ
                  </button>
                  <button
                    type="submit"
                    disabled={authLoading}
                    className="bg-google-blue hover:bg-google-blueDark text-white px-6 py-2.5 rounded-material-full text-[14px] font-medium shadow-material-btn min-w-[96px] h-9 disabled:opacity-60 transition-shadow duration-200"
                  >
                    {authLoading ? <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin inline-block" /> : "Lưu mật khẩu"}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      </div>
    );
  }

  if (showReset) {
    return (
      <div className="min-h-screen bg-surface-dim flex">
        <div className="hidden lg:flex w-[52%] bg-gradient-to-br from-google-blue via-google-blueLight to-google-blueDark p-12 text-white flex-col justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 bg-white/20 rounded-material flex items-center justify-center">
              <DocIcon size={20} className="text-white" />
            </div>
            <span className="text-[15px] font-medium">Smart Document</span>
          </div>
          <div className="my-auto">
            <h2 className="text-[40px] leading-[48px] font-normal tracking-tight">Đặt lại mật khẩu</h2>
            <p className="text-[16px] text-white/80 mt-4 max-w-[360px] leading-6">Nhập email để nhận liên kết đặt lại mật khẩu</p>
          </div>
          <div className="text-white/60 text-[12px]">&copy; 2026 Smart Document Chatbot &bull; Enterprise CRAG</div>
        </div>
        <div className="flex-1 flex items-center justify-center p-6">
          <div className="w-full max-w-[448px]">
            <div className="lg:hidden flex items-center gap-3 mb-8">
              <div className="w-9 h-9 bg-google-blue rounded-material flex items-center justify-center">
                <DocIcon size={20} className="text-white" />
              </div>
              <span className="text-[15px] font-medium text-onsurface">Smart Document</span>
            </div>
            <h1 className="text-[24px] leading-8 text-onsurface font-normal">Đặt lại mật khẩu</h1>
            <p className="text-[14px] text-onsurface-muted mt-1">Nhập email để nhận hướng dẫn đặt lại mật khẩu</p>
            {resetSent ? (
              <div className="mt-6 p-4 bg-[#e6f4ea] border border-google-green rounded-material text-google-green text-[14px] flex items-center gap-2">
                <CheckIcon />
                <span>Liên kết đặt lại mật khẩu đã đƱợc gửi đến email của bạn</span>
              </div>
            ) : (
              <form onSubmit={handleReset} className="mt-6 space-y-4">
                <div className="relative">
                  <input type="email" value={resetEmail} onChange={(e) => setResetEmail(e.target.value)} placeholder="Email" className="peer w-full px-3.5 py-3.5 border border-outline rounded-material text-[16px] placeholder-transparent focus:outline-none focus:border-google-blue focus:ring-1 focus:ring-google-blue" />
                  <label className="absolute left-3 -top-2.5 bg-white px-1 text-[12px] text-google-blue peer-placeholder-shown:top-3.5 peer-placeholder-shown:text-[16px] peer-placeholder-shown:text-onsurface-muted peer-focus:-top-2.5 peer-focus:text-[12px] peer-focus:text-google-blue transition-all duration-200">Email</label>
                </div>
                {authError && (
                  <div className="flex gap-2 items-start bg-[#fce8e6] border border-[#f5c6cb] text-[#a50e0e] text-[13px] px-3 py-2.5 rounded-material">
                    <ErrorIcon />
                    <span>{authError}</span>
                  </div>
                )}
                <div className="flex items-center justify-between pt-2">
                  <button type="button" onClick={() => setShowReset(false)} className="text-google-blue text-[14px] font-medium px-3 py-2 hover:bg-surface-container rounded-material-full">Quay lại đăng nhập</button>
                  <button type="submit" disabled={authLoading} className="bg-google-blue hover:bg-google-blueDark text-white px-6 py-2.5 rounded-material-full text-[14px] font-medium shadow-material-btn min-w-[96px] h-9 disabled:opacity-60 transition-shadow duration-200">
                    {authLoading ? <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin inline-block" /> : "Gửi liên kết"}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-surface-dim flex">
      <div className="hidden lg:flex w-[52%] bg-gradient-to-br from-google-blue via-google-blueLight to-google-blueDark p-12 text-white flex-col justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 bg-white/20 rounded-material flex items-center justify-center">
            <DocIcon size={20} className="text-white" />
          </div>
          <span className="text-[15px] font-medium">Smart Document</span>
        </div>
        <div className="my-auto">
          <h2 className="text-[40px] leading-[48px] font-normal tracking-tight">
            {authMode === "login" ? "Chào mừng trở lại" : "Tạo tài khoản"}
          </h2>
          <p className="text-[16px] text-white/80 mt-4 max-w-[360px] leading-6">
            {authMode === "login"
              ? "Đăng nhập để tiếp tục với Smart Document Chatbot"
              : "Bắt đầu hành trình của bạn với nền tảng trí tuệ nhân tạo"}
          </p>
        </div>
        <div className="text-white/60 text-[12px]">&copy; 2026 Smart Document Chatbot &bull; Enterprise CRAG</div>
      </div>

      <div className="flex-1 flex items-center justify-center p-6">
        <div className="w-full max-w-[448px]">
          <div className="lg:hidden flex items-center gap-3 mb-8">
            <div className="w-9 h-9 bg-google-blue rounded-material flex items-center justify-center">
              <DocIcon size={20} className="text-white" />
            </div>
            <span className="text-[15px] font-medium text-onsurface">Smart Document</span>
          </div>

          <h1 className="text-[24px] leading-8 text-onsurface font-normal text-center">
            {authMode === "login" ? "Chào mừng trở lại" : "Tạo tài khoản"}
          </h1>
          <p className="text-[14px] text-onsurface-muted text-center mt-1">
            {authMode === "login" ? "Đăng nhập để tiếp tục Smart Doc" : "Bắt đầu với Smart Doc miễn phí"}
          </p>

          <form onSubmit={handleAuthSubmit} className="mt-8 space-y-5">
            <div className="relative">
              <input value={authUsername} onChange={(e) => setAuthUsername(e.target.value)} placeholder="Email hoặc tên đăng nhập" className="peer w-full px-3.5 py-3.5 border border-outline rounded-material text-[14px] text-onsurface placeholder-transparent focus:outline-none focus:border-google-blue focus:ring-1 focus:ring-google-blue bg-white" />
              <label className="absolute left-3 -top-2 bg-white px-1 text-[12px] text-google-blue peer-placeholder-shown:top-3.5 peer-placeholder-shown:text-[14px] peer-placeholder-shown:text-onsurface-muted peer-focus:-top-2 peer-focus:text-[12px] peer-focus:text-google-blue transition-all duration-200">Email hoặc tên đăng nhập</label>
            </div>

            <div className="relative">
              <input type="password" value={authPassword} onChange={(e) => setAuthPassword(e.target.value)} placeholder="Mật khẩu" className="peer w-full px-3.5 py-3.5 border border-outline rounded-material text-[14px] text-onsurface placeholder-transparent focus:outline-none focus:border-google-blue focus:ring-1 focus:ring-google-blue bg-white" />
              <label className="absolute left-3 -top-2 bg-white px-1 text-[12px] text-google-blue peer-placeholder-shown:top-3.5 peer-placeholder-shown:text-[14px] peer-placeholder-shown:text-onsurface-muted peer-focus:-top-2 peer-focus:text-[12px] peer-focus:text-google-blue transition-all duration-200">Mật khẩu</label>
              {authMode === "register" && <PasswordStrength password={authPassword} />}
            </div>

            {authMode === "register" && (
              <div className="relative">
                <input type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} placeholder="Xác nhận mật khẩu" className="peer w-full px-3.5 py-3.5 border border-outline rounded-material text-[14px] placeholder-transparent focus:outline-none focus:border-google-blue focus:ring-1 focus:ring-google-blue bg-white" />
                <label className="absolute left-3 -top-2 bg-white px-1 text-[12px] text-google-blue peer-placeholder-shown:top-3.5 peer-placeholder-shown:text-[14px] peer-placeholder-shown:text-onsurface-muted peer-focus:-top-2 peer-focus:text-[12px] peer-focus:text-google-blue transition-all duration-200">Xác nhận mật khẩu</label>
              </div>
            )}

            {authMode === "login" && (
              <div className="-mt-1">
                <button type="button" onClick={() => setShowReset(true)} className="text-google-blue text-[13px] font-medium hover:underline">Quên mật khẩu?</button>
              </div>
            )}

            {authError && (
              <div className="flex gap-2 items-start bg-[#fce8e6] border border-[#f5c6cb] text-[#a50e0e] text-[13px] px-3 py-2.5 rounded-material">
                <ErrorIcon />
                <span>{authError}</span>
              </div>
            )}

            <div className="flex items-center justify-between pt-1">
              <button type="button" onClick={switchMode} className="text-google-blue text-[14px] font-medium hover:bg-surface-container px-3 py-2 rounded-material-full transition-colors duration-200">
                {authMode === "login" ? "Tạo tài khoản" : "Đã có tài khoản?"}
              </button>
              <button type="submit" disabled={authLoading} className="bg-google-blue hover:bg-google-blueDark hover:shadow-material-btn-hover text-white text-[14px] font-medium px-6 py-2.5 rounded-material-full min-w-[88px] h-9 disabled:opacity-60 transition-all duration-200">
                {authLoading ? <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin inline-block" /> : "Tiếp tục"}
              </button>
            </div>
          </form>

          <div className="flex items-center gap-3 my-6">
            <div className="h-[1px] flex-1 bg-outline" />
            <span className="text-onsurface-muted text-[13px]">hoặc</span>
            <div className="h-[1px] flex-1 bg-outline" />
          </div>

          <button onClick={handleGoogleLogin} className="w-full flex items-center justify-center gap-3 py-2.5 border border-outline rounded-material-full hover:bg-surface-dim text-onsurface-variant text-[14px] font-medium hover:shadow-material-btn transition-all duration-200">
            <GoogleLogo />
            Tiếp tục với Google
          </button>

          <div className="mt-6 text-[11px] text-onsurface-muted text-center leading-4">
            Bằng việc tiếp tục, bạn đồng ý với Điều khoản &amp; Chính sách.<br />
            Smart Doc &bull; Enterprise CRAG &bull; Cloudflare Pages &bull; Render
          </div>
        </div>
      </div>

      {googleModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setGoogleModalOpen(false)}>
          <div className="bg-white rounded-material-lg shadow-material-3 p-8 max-w-sm w-[90%] text-center" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-[16px] font-medium text-onsurface mb-1">Đăng nhập bằng Google</h3>
            <p className="text-[13px] text-onsurface-muted mb-5">Chọn tài khoản Google trong cửa sổ bật lên.</p>
            <div className="flex justify-center" ref={googleBtnRef} />
            {!GOOGLE_CLIENT_ID && (
              <p className="text-[13px] text-google-red mt-4">Chưa cấu hình Google Login trên máy chủ.</p>
            )}
            <button onClick={() => setGoogleModalOpen(false)} className="mt-5 text-google-blue text-[14px] font-medium px-4 py-2 rounded-material-full hover:bg-surface-container">Đóng</button>
          </div>
        </div>
      )}
    </div>
  );
}

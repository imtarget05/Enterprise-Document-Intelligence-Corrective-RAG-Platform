/* eslint-disable react-refresh/only-export-components */
import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  type ReactNode,
} from "react";
import { API_BASE_URL } from "./apiConfig";

interface AuthContextType {
  token: string | null;
  username: string | null;
  role: string | null;
  login: (token: string | null, username: string, role: string) => void;
  logout: () => void;
  isAuthenticated: boolean;
  isAdmin: boolean;
  isEngineer: boolean;
  isViewer: boolean;
  isInitializing: boolean;
}

export const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => {
    try {
      return sessionStorage.getItem("smartdoc_jwt");
    } catch {
      return null;
    }
  });
  const [username, setUsername] = useState<string | null>(null);
  const [role, setRole] = useState<string | null>(null);
  const [isInitializing, setIsInitializing] = useState(true);

  useEffect(() => {
    // Clean up any legacy localStorage entry
    try {
      localStorage.removeItem("smartdoc.auth");
    } catch {
      // ignore
    }

    let cancelled = false;
    (async () => {
      try {
        const headers: Record<string, string> = {};
        const savedToken = sessionStorage.getItem("smartdoc_jwt");
        if (savedToken) {
          headers["Authorization"] = `Bearer ${savedToken}`;
        }
        const res = await fetch(`${API_BASE_URL}/auth/me`, {
          credentials: "include",
          headers,
        });
        if (cancelled) return;
        if (res.ok) {
          const data = await res.json();
          setUsername(data.username ?? null);
          setRole(data.role ?? null);
          if (data.token) {
            setToken(data.token);
            try { sessionStorage.setItem("smartdoc_jwt", data.token); } catch {}
          }
        } else {
          setUsername(null);
          setRole(null);
          setToken(null);
          try { sessionStorage.removeItem("smartdoc_jwt"); } catch {}
        }
      } catch {
        if (!cancelled) {
          setUsername(null);
          setRole(null);
          setToken(null);
        }
      } finally {
        if (!cancelled) {
          setIsInitializing(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(
    (newToken: string | null, newUsername: string, newRole: string) => {
      setToken(newToken);
      if (newToken) {
        try {
          sessionStorage.setItem("smartdoc_jwt", newToken);
        } catch {
          // ignore
        }
      }
      setUsername(newUsername);
      setRole(newRole);
    },
    [],
  );

  const logout = useCallback(() => {
    const savedToken = token;
    setToken(null);
    setUsername(null);
    setRole(null);
    try {
      sessionStorage.removeItem("smartdoc_jwt");
    } catch {
      // ignore
    }
    const headers: Record<string, string> = {};
    if (savedToken) {
      headers["Authorization"] = `Bearer ${savedToken}`;
    }
    void fetch(`${API_BASE_URL}/auth/logout`, {
      method: "POST",
      credentials: "include",
      headers,
    }).catch(() => {
      // ignore network errors on logout
    });
  }, [token]);

  const isAuthenticated = !!username;
  const isAdmin = role === "ROLE_ADMIN" || role === "ADMIN";
  const isEngineer = role === "ROLE_ENGINEER" || role === "ENGINEER";
  const isViewer = role === "ROLE_VIEWER" || role === "VIEWER";

  return (
    <AuthContext.Provider
      value={{
        token,
        username,
        role,
        login,
        logout,
        isAuthenticated,
        isAdmin,
        isEngineer,
        isViewer,
        isInitializing,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}

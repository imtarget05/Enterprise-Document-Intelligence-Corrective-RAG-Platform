import { Suspense, lazy, useState, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider, useAuth } from "./context/AuthContext";
import ErrorBoundary from "./components/ErrorBoundary";
import "./App.css";

// Route-level code splitting: each page bundles into its own chunk so the
// login screen loads instantly without pulling in the chat/document code.
const LoginPage = lazy(() => import("./pages/LoginPage"));
const ChatPage = lazy(() => import("./pages/ChatPage"));
const AdminPage = lazy(() => import("./pages/AdminPage"));

type AppView = "chat" | "admin";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30000,
      retry: 1,
    },
  },
});

// Minimal Material-style loading indicator while a lazy chunk streams in.
function RouteFallback() {
  return (
    <div
      className="min-h-screen flex items-center justify-center bg-surface"
      role="status"
      aria-label="Đang tải"
    >
      <span className="w-8 h-8 border-2 border-google-blue border-t-transparent rounded-full animate-spin" />
    </div>
  );
}

function SuspensePage({ children }: { children: ReactNode }) {
  return <Suspense fallback={<RouteFallback />}>{children}</Suspense>;
}

function AppContent() {
  const { isAuthenticated, isInitializing } = useAuth();
  const [view, setView] = useState<AppView>("chat");

  // Don't flash the login page while we restore a persisted session.
  if (isInitializing) {
    return <RouteFallback />;
  }

  if (!isAuthenticated) {
    return (
      <SuspensePage>
        <LoginPage />
      </SuspensePage>
    );
  }

  // Persist view choice on the window so UserMenu/Header can switch views
  (window as unknown as { __appView?: [AppView, (v: AppView) => void] }).__appView = [view, setView];

  return (
    <ErrorBoundary>
      <SuspensePage>
        {view === "admin" && <AdminPage currentView={view} onViewChange={setView} />}
        {view === "chat" && <ChatPage currentView={view} onViewChange={setView} />}
      </SuspensePage>
    </ErrorBoundary>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <AppContent />
      </AuthProvider>
    </QueryClientProvider>
  );
}
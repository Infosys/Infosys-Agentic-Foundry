import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import Cookies from "js-cookie";
import { useNavigate } from "react-router-dom";

// Centralized Auth Context: single source of truth for auth + role
// Simplified to avoid many files. Derives auth state from cookies.

const AuthContext = createContext({
  isAuthenticated: false,
  user: null,
  role: null,
  sessionId: null,
  loading: true,
  login: () => {},
  logout: () => {},
});

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [role, setRole] = useState(null);
  const [sessionId, setSessionId] = useState(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  // Hydrate from cookies once on mount
  useEffect(() => {
    const name = Cookies.get("userName") || null;
    const r = Cookies.get("role") || null;
    let sid = Cookies.get("user_session") || null;
    if (!sid) {
      // fallback to localStorage (in case cookie blocked or lost)
      sid = typeof window !== "undefined" ? window.localStorage.getItem("user_session") : null;
    }
    setUser(name);
    setRole(r);
    setSessionId(sid);
    setLoading(false);
  }, []);

  const login = useCallback((payload) => {
    if (!payload || typeof payload !== "object") return;
    const { userName, role: newRole } = payload;
    // Accept multiple possible backend key names for session id
    const sessionCandidate = payload.user_session || payload.session_id || payload.sessionId || payload.session || null;
    if (userName) {
      Cookies.set("userName", userName, { path: "/" });
      setUser(userName);
    }
    if (newRole) {
      Cookies.set("role", newRole, { path: "/" });
      setRole(newRole);
    }
    if (sessionCandidate) {
      Cookies.set("user_session", sessionCandidate, { path: "/" });
      try {
        window.localStorage.setItem("user_session", sessionCandidate);
      } catch (_) {}
      setSessionId(sessionCandidate);
    }
  }, []);

  const logout = useCallback(
    (redirectPath = "/login") => {
      Cookies.remove("userName", { path: "/" });
      Cookies.remove("user_session", { path: "/" });
      Cookies.remove("role", { path: "/" });
      Cookies.remove("jwt-token");
      Cookies.remove("email");
      try {
        window.localStorage.removeItem("user_session");
      } catch (_) {}
      setUser(null);
      setRole(null);
      setSessionId(null);
      navigate(redirectPath, { replace: true }); // NEW
    },
    [navigate]
  );

  // const isAuthenticated = !!user && !!sessionId; // require both for now; sessionId now more robust

  const isAuthenticated = !!user;

  const value = useMemo(
    () => ({
      isAuthenticated,
      user,
      role,
      loading,
      sessionId,
      login,
      logout,
    }),
    [isAuthenticated, user, role, loading, sessionId, login, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => useContext(AuthContext);

export default AuthContext;

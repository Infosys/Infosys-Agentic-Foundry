import { useEffect, useRef } from "react";
import { useAuth } from "../context/AuthContext";
import Cookies from "js-cookie";

// Session timeout: 5 hours 59 minutes (just under 6h) in ms
const SESSION_TIMEOUT_MS = (5 * 60 * 60 + 59 * 60) * 1000; // 21,540,000 ms

const LOGIN_TS_KEY = "login_timestamp";

// Persist timestamp when user logs in
export const setSessionStart = () => {
  try {
    const now = Date.now();
    localStorage.setItem(LOGIN_TS_KEY, String(now));
    Cookies.set(LOGIN_TS_KEY, String(now)); // optional cookie mirror
  } catch (_) {}
};

// Hook: auto logout user exactly after 6 hours since login timestamp
export default function useAutoLogout() {
  const { logout, isAuthenticated } = useAuth();
  const timerRef = useRef(null);

  useEffect(() => {
    if (!isAuthenticated) return; // only when logged in

    const ensureTimestamp = () => {
      let ts = localStorage.getItem(LOGIN_TS_KEY);
      if (!ts) {
        setSessionStart();
        ts = localStorage.getItem(LOGIN_TS_KEY);
      }
      return Number(ts);
    };

    const doLogout = () => {
      try {
        localStorage.removeItem(LOGIN_TS_KEY);
        Cookies.remove(LOGIN_TS_KEY);
      } catch (_) {}
      logout();
      // No hard reload needed; ProtectedRoute will redirect to /login automatically.
    };

    const schedule = () => {
      clearTimeout(timerRef.current);
      const ts = ensureTimestamp();
      if (!ts) return; // safety
      const elapsed = Date.now() - ts;
      if (elapsed >= SESSION_TIMEOUT_MS) {
        console.log("loggedOut Due to UI session timeOut");
        doLogout();
        return;
      }
      const remaining = SESSION_TIMEOUT_MS - elapsed;
      timerRef.current = setTimeout(doLogout, remaining);
    };

    schedule();

    // Also re-check on visibility return (covers sleep / clock changes)
    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        schedule();
      }
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      clearTimeout(timerRef.current);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [isAuthenticated, logout]);
}

import { useEffect, useRef, useCallback } from "react";
import { useAuth } from "../context/AuthContext";

const IDLE_TIMEOUT_MS = 20 * 60 * 1000; // 20 minutes of inactivity

const ACTIVITY_EVENTS = [
  "mousemove",
  "mousedown",
  "keydown",
  "touchstart",
  "scroll",
  "click",
];

export default function useIdleTimeout() {
  const { logout, isAuthenticated } = useAuth();
  const timerRef = useRef(null);

  const doLogout = useCallback(() => {
    logout("idle-timeout");
  }, [logout]);

  const resetTimer = useCallback(() => {
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(doLogout, IDLE_TIMEOUT_MS);
  }, [doLogout]);

  useEffect(() => {
    if (!isAuthenticated) {
      clearTimeout(timerRef.current);
      return;
    }

    resetTimer();

    ACTIVITY_EVENTS.forEach((evt) =>
      window.addEventListener(evt, resetTimer, { passive: true })
    );

    // Re-arm on tab focus — the timer may have fired while the tab was hidden
    const onVisibility = () => {
      if (document.visibilityState === "visible") resetTimer();
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      clearTimeout(timerRef.current);
      ACTIVITY_EVENTS.forEach((evt) =>
        window.removeEventListener(evt, resetTimer)
      );
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [isAuthenticated, resetTimer]);
}

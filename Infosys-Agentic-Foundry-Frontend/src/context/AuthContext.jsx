import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import Cookies from "js-cookie";
import { useNavigate } from "react-router-dom";
// import { useMessage } from "../Hooks/MessageContext";

// Enhanced Auth Context with single-session & cross-tab coordination

let tabIdCounter = 0;

// Helper utilities (internal)
const getCookie = (name) => {
  try {
    return Cookies.get(name) || null;
  } catch (_) {
    return null;
  }
};

const setCookie = (name, value, options = {}) => {
  try {
    // Set 6-hour expiration to match session timeout (0.25 days = 6 hours)
    const defaultOptions = {
      path: "/",
      expires: 0.25, // 6 hours
      sameSite: "Lax",
      ...options,
    };
    Cookies.set(name, value, defaultOptions);
  } catch (_) {}
};

const deleteCookie = (name) => {
  try {
    Cookies.remove(name, { path: "/" });
  } catch (_) {}
};

// Minimal localStorage helpers (guarding SSR)
const lsGet = (k) => {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(k);
  } catch (_) {
    return null;
  }
};
const lsSet = (k, v) => {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(k, v);
  } catch (_) {}
};
const lsRemove = (k) => {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(k);
  } catch (_) {}
};

// Core artifact checks (strict by default). If strict=false, only require userName + user_session.
const hasAuthArtifacts = (strict = true) => {
  const userName = getCookie("userName");
  const session = getCookie("user_session");
  const jwt = getCookie("jwt-token");
  if (!strict) return !!(userName && session);
  return !!(userName && session && jwt);
};

const getActiveUser = () => {
  return getCookie("userName") || lsGet("active_user_name") || null;
};

const setActiveUser = (name) => {
  if (!name) return;
  setCookie("userName", name, { expires: 0.25 }); // 6 hours
  lsSet("active_user_name", name);
};

const clearAuthArtifacts = () => {
  deleteCookie("userName");
  deleteCookie("jwt-token");
  deleteCookie("user_session");
  deleteCookie("role");
  deleteCookie("refresh-token");
  deleteCookie("email");
  lsRemove("active_user_name");
  lsRemove("user_session");
};

// Broadcast channel constants
const CHANNEL_NAME = "auth_channel";
const FALLBACK_STORAGE_KEY = "auth_event"; // ephemeral single-use

const AuthContext = createContext({
  isAuthenticated: false,
  user: null, // { name, role }
  role: null,
  sessionId: null,
  loading: true,
  // API
  login: () => {},
  logout: () => {},
  forceReplaceLogin: () => {},
  syncFromCookies: () => {},
  // Helpers exposed (may be used externally e.g. LoginScreen / ProtectedRoute)
  hasAuthArtifacts,
  getActiveUser,
});

export const AuthProvider = ({ children }) => {
  const navigate = useNavigate();

  // Tab identity
  const tabIdRef = useRef(`tab-${++tabIdCounter}-${Date.now()}`);
  const channelRef = useRef(null);
  const mountedRef = useRef(false);

  const [userState, setUserState] = useState(null); // { name, role }
  const [sessionId, setSessionId] = useState(null);
  const [loading, setLoading] = useState(true);

  // Derived role for backward compatibility
  const role = userState?.role || getCookie("role") || null;

  // Hydration
  const syncFromCookies = useCallback(() => {
    const name = getActiveUser();
    const r = getCookie("role") || null;
    const sid = getCookie("user_session") || lsGet("user_session");
    if (name && r && hasAuthArtifacts()) {
      setUserState({ name, role: r });
    } else if (!hasAuthArtifacts()) {
      setUserState(null);
    }
    setSessionId(sid);
  }, []);

  useEffect(() => {
    syncFromCookies();
    setLoading(false);
  }, [syncFromCookies]);

  // Broadcast helper (safe metadata only)
  const broadcast = useCallback((type, payload = {}) => {
    const message = {
      type,
      userName: getActiveUser(),
      role: getCookie("role") || null,
      ts: Date.now(),
      sourceTabId: tabIdRef.current,
      ...payload,
    };
    // Primary: BroadcastChannel
    try {
      if (channelRef.current) {
        channelRef.current.postMessage(message);
      }
    } catch (_) {}
    // Fallback: localStorage single-use event
    try {
      window.localStorage.setItem(FALLBACK_STORAGE_KEY, JSON.stringify(message));
      // Remove shortly to enable subsequent identical events
      setTimeout(() => {
        try {
          window.localStorage.removeItem(FALLBACK_STORAGE_KEY);
        } catch (_) {}
      }, 50);
    } catch (_) {}
  }, []);

  // Internal logout (no redirect management here unless reason indicates)
  const performLogoutStateClear = useCallback(() => {
    setUserState(null);
    setSessionId(null);
  }, []);

  const internalLogout = useCallback(
    (reason = "internal") => {

      clearAuthArtifacts();
      performLogoutStateClear();
      broadcast("LOGOUT", { reason });
      // Only navigate if currently not on /login to avoid loops
      if (window.location.pathname !== "/login") {
        navigate("/login", { replace: true });
      }
    },
    [broadcast, navigate, performLogoutStateClear]
  );

  const login = useCallback(
    (payload) => {
      if (!payload || typeof payload !== "object") return;
      const { userName, role: newRole, refresh_token } = payload;
      const sessionCandidate = payload.user_session || payload.session_id || payload.sessionId || payload.session || null;

      if (userName) {
        setActiveUser(userName);
      }
      if (newRole) setCookie("role", newRole, { expires: 0.25 });
      if (sessionCandidate) {
        setCookie("user_session", sessionCandidate, { expires: 0.25 });
        lsSet("user_session", sessionCandidate);
        setSessionId(sessionCandidate);
      }
      if (refresh_token) setCookie("refresh-token", refresh_token, { expires: 0.25 });

      // Update state after artifacts to align with validator
      setUserState({ name: userName, role: newRole });
      broadcast("LOGIN");
    },
    [broadcast]
  );

  const forceReplaceLogin = useCallback(
    (credentials) => {
      // Notify others to logout immediately
      broadcast("REPLACE_SESSION", { targetUser: credentials?.userName });
      // Proceed with normal login flow
      login(credentials);
    },
    [broadcast, login]
  );

  const logout = useCallback(
    (reason = "manual", redirectPath = "/login") => {

      clearAuthArtifacts();
      performLogoutStateClear();
      broadcast("LOGOUT", { reason });
      navigate(redirectPath, { replace: true });
    },
    [broadcast, navigate, performLogoutStateClear]
  );

  // Cross-tab listeners
  useEffect(() => {
    if (mountedRef.current) return; // ensure single setup
    mountedRef.current = true;
    try {
      channelRef.current = new BroadcastChannel(CHANNEL_NAME);
      channelRef.current.onmessage = (ev) => {
        const msg = ev.data || {};
        if (!msg || msg.sourceTabId === tabIdRef.current) return; // ignore self
        switch (msg.type) {
          case "LOGOUT":
            performLogoutStateClear();
            // Ensure artifacts cleared locally (in case broadcast arrived first)
            clearAuthArtifacts();
            if (window.location.pathname !== "/login") navigate("/login", { replace: true });
            break;
          case "REPLACE_SESSION":
            // Another tab is replacing session; logout silently
            performLogoutStateClear();
            clearAuthArtifacts();
            if (window.location.pathname !== "/login") navigate("/login", { replace: true });
            break;
          case "LOGIN":
            // Sync only if we are unauthenticated & artifacts exist
            if (!hasAuthArtifacts()) return;
            if (!userState?.name) syncFromCookies();
            break;
          case "PING":
          default:
            break;
        }
      };
    } catch (_) {
      // BroadcastChannel unsupported
    }

    // Fallback storage event
    const onStorage = (e) => {
      if (e.key !== FALLBACK_STORAGE_KEY || !e.newValue) return;
      try {
        const msg = JSON.parse(e.newValue);
        if (msg.sourceTabId === tabIdRef.current) return;
        // Reuse same logic by simulating onmessage
        channelRef.current?.onmessage?.({ data: msg });
      } catch (_) {}
    };
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener("storage", onStorage);
      try {
        channelRef.current && channelRef.current.close();
      } catch (_) {}
    };
  }, [navigate, performLogoutStateClear, syncFromCookies, userState]);

  // Cookie Monitoring - Detect when cookies disappear unexpectedly
  useEffect(() => {
    if (!userState?.name) return;

    // Monitor cookie changes every 5 seconds when authenticated
    const cookieMonitor = setInterval(() => {
    }, 5000); // Check every 5 seconds

    return () => clearInterval(cookieMonitor);
  }, [userState]);

  // Track who is deleting cookies - Catch the culprit!
  useEffect(() => {
    if (!userState?.name) return;

    // Wrap Cookies.remove to catch deletions
    const originalRemove = Cookies.remove;
    const originalSet = Cookies.set;

    Cookies.remove = function (name, options) {
      const stack = new Error().stack;
      console.error("🚨 COOKIES.REMOVE CALLED!", {
        cookieName: name,
        timestamp: new Date().toISOString(),
        callStack: stack,
      });
      return originalRemove.call(this, name, options);
    };

    Cookies.set = function (name, value, options) {
      // Check if being set to expire immediately (deletion via set with maxAge=0 or expires in past)
      if (options?.expires === 0 || options?.["max-age"] === 0 || options?.maxAge === 0) {
        console.error("🚨 COOKIE BEING SET TO EXPIRE IMMEDIATELY (DELETION)!", {
          cookieName: name,
          value,
          options,
          timestamp: new Date().toISOString(),
          callStack: new Error().stack,
        });
      }
      // Log if setting empty value (another form of deletion)
      if (value === "" || value === null || value === undefined) {
        console.warn("⚠️ COOKIE BEING SET TO EMPTY VALUE!", {
          cookieName: name,
          value,
          options,
          timestamp: new Date().toISOString(),
          callStack: new Error().stack,
        });
      }
      return originalSet.call(this, name, value, options);
    };

    return () => {
      Cookies.remove = originalRemove;
      Cookies.set = originalSet;
    };
  }, [userState]);

  // Monitor direct document.cookie modifications (bypassing js-cookie)
  useEffect(() => {
    if (!userState?.name) return;

    let lastCookieSnapshot = document.cookie;

    const cookieWatcher = setInterval(() => {
      const currentCookies = document.cookie;

      if (currentCookies !== lastCookieSnapshot) {
        // Parse both to find what changed
        const lastCookieObj = {};
        const currentCookieObj = {};

        lastCookieSnapshot.split(";").forEach((cookie) => {
          const [key, value] = cookie.trim().split("=");
          if (key) lastCookieObj[key] = value;
        });

        currentCookies.split(";").forEach((cookie) => {
          const [key, value] = cookie.trim().split("=");
          if (key) currentCookieObj[key] = value;
        });


        lastCookieSnapshot = currentCookies;
      }
    }, 1000); // Check every second

    return () => clearInterval(cookieWatcher);
  }, [userState]);

  // Track last time all strict artifacts were present (for grace period if jwt temporarily missing during refresh)
  const lastGoodArtifactsRef = useRef(Date.now());

  // Validation triggers (focus, visibility, online, click, interval)
  useEffect(() => {
    let debounceTimer = null;

    const validate = () => {
      const strictArtifactsPresent = hasAuthArtifacts(true);
      const coreArtifactsPresent = hasAuthArtifacts(false);
      const activeUser = getActiveUser();

      // Immediate failure if core artifacts missing (user/session)
      if (!coreArtifactsPresent) {
        if (userState) {
          internalLogout("missing-core-artifacts");
        }
        return;
      }

      // Grace period for missing jwt-token only (possible rotation window)
      if (!strictArtifactsPresent) {
        const now = Date.now();
        const graceMs = 10000; // 10 seconds tolerance
        if (now - lastGoodArtifactsRef.current > graceMs) {
          internalLogout("missing-jwt-token");
        }
        return; // wait for next cycle
      }

      // Update last good timestamp
      lastGoodArtifactsRef.current = Date.now();

      if (userState?.name && activeUser && userState.name !== activeUser) {
        // Special case: allow seamless upgrade from Guest -> real user without global logout
        if (userState.name === "Guest") {
          syncFromCookies();
          return;
        }
        internalLogout("mismatch-active-user");
        return;
      }

      if (strictArtifactsPresent && !userState) syncFromCookies();
    };

    // DEBOUNCED validator for click events to prevent excessive validation
    const debouncedValidate = () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(validate, 300); // 300ms debounce
    };

    window.addEventListener("focus", validate);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") validate();
    });
    window.addEventListener("online", validate);

    // Use debounced version for clicks to prevent false-positive logouts
    document.addEventListener("click", debouncedValidate, true);

    const interval = setInterval(validate, 60000);

    return () => {
      clearTimeout(debounceTimer);
      window.removeEventListener("focus", validate);
      window.removeEventListener("online", validate);
      document.removeEventListener("visibilitychange", validate);
      document.removeEventListener("click", debouncedValidate, true);
      clearInterval(interval);
    };
  }, [internalLogout, syncFromCookies, userState]);

  // isAuthenticated: require core artifacts and alignment (not necessarily jwt-token to allow refresh grace)
  const isAuthenticated = !!(userState?.name && hasAuthArtifacts(false) && getActiveUser() === userState.name);

  const value = useMemo(
    () => ({
      isAuthenticated,
      user: userState ? { name: userState.name, role: userState.role } : null,
      // Backwards compatibility
      userName: userState?.name || null,
      role,
      sessionId,
      loading,
      login,
      logout,
      internalLogout, // optional external usage
      forceReplaceLogin,
      syncFromCookies,
      // helpers
      hasAuthArtifacts: (strict) => hasAuthArtifacts(strict),
      getActiveUser,
    }),
    [isAuthenticated, userState, role, sessionId, loading, login, logout, internalLogout, forceReplaceLogin, syncFromCookies]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => useContext(AuthContext);
export { hasAuthArtifacts, getActiveUser, setActiveUser, clearAuthArtifacts };
export default AuthContext;

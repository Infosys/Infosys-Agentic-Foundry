import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import Cookies from "js-cookie";
import { useNavigate } from "react-router-dom";
import authStorage from "../utils/authStorage";
import { clearMyDepartmentsCache } from "../services/myDepartmentsService";
import { APIs } from "../constant";
import useFetch from "../Hooks/useAxios";
import { msalInstance } from "../auth/msalConfig";
import {
  clearMsalSession,
  isMsalLoginPending,
  suppressMsalAutoLogin,
} from "../auth/msalSessionUtils";
// import { useMessage } from "../Hooks/MessageContext";

// Enhanced Auth Context with single-session & cross-tab coordination

let tabIdCounter = 0;

// Helper utilities (internal)
const getCookie = (name) => {
  try {
    // Read from localStorage first, fallback to cookie for migration
    const keyMap = {
      "userName": () => authStorage.getUserName(),
      "role": () => authStorage.getRole(),
      "user_session": () => authStorage.getSession(),
      "jwt-token": () => authStorage.getJwt(),
      "refresh-token": () => authStorage.getRefresh(),
      "email": () => authStorage.getEmail(),
    };
    const getter = keyMap[name];
    if (getter) {
      return getter() || Cookies.get(name) || null;
    }
    return Cookies.get(name) || null;
  } catch (_) {
    return null;
  }
};

const setCookie = (name, value, options = {}) => {
  try {
    // Store in localStorage (persists across restarts)
    const keyMap = {
      "userName": () => authStorage.setUserName(value),
      "role": () => authStorage.setRole(value),
      "user_session": () => authStorage.setSession(value),
      "jwt-token": () => authStorage.setJwt(value),
      "refresh-token": () => authStorage.setRefresh(value),
      "email": () => authStorage.setEmail(value),
      "department_name": () => authStorage.setDepartment(value),
      "department": () => authStorage.setDepartment(value),
    };
    const setter = keyMap[name];
    if (setter) {
      setter();
    }
    // Also set cookie as fallback for any code still reading from cookies
    const defaultOptions = {
      path: "/",
      expires: 14,
      sameSite: "Strict",
      secure: typeof window !== "undefined" && window.location.protocol === "https:",
      ...options,
    };
    Cookies.set(name, value, defaultOptions);
  } catch (_) { }
};

const deleteCookie = (name) => {
  try {
    const keyMap = {
      "userName": () => authStorage.removeUserName(),
      "role": () => authStorage.removeRole(),
      "user_session": () => authStorage.removeSession(),
      "jwt-token": () => authStorage.removeJwt(),
      "refresh-token": () => authStorage.removeRefresh(),
      "email": () => authStorage.removeEmail(),
      "department_name": () => authStorage.removeDepartment(),
      "department": () => authStorage.removeDepartment(),
    };
    const remover = keyMap[name];
    if (remover) remover();
    Cookies.remove(name, { path: "/" });
  } catch (_) { }
};

// Minimal localStorage helpers (guarding SSR) — for non-sensitive keys only
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
  } catch (_) { }
};
const lsRemove = (k) => {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(k);
  } catch (_) { }
};

// sessionStorage helpers for sensitive identity data that should not persist
// across browser sessions (tab-scoped, cleared when the browser is closed)
const ssGet = (k) => {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(k);
  } catch (_) {
    return null;
  }
};
const ssSet = (k, v) => {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(k, v);
    window.localStorage.removeItem(k); // remove any stale localStorage copy
  } catch (_) { }
};
const ssRemove = (k) => {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(k);
    window.localStorage.removeItem(k); // clean up legacy copy
  } catch (_) { }
};

// Core artifact checks (strict by default). If strict=false, only require userName + user_session.
// Also checks localStorage as fallback since browsers may temporarily hide cookies on tab switch.
const hasAuthArtifacts = (strict = true) => {
  const userName = authStorage.getUserName() || getCookie("userName");
  const session = authStorage.getSession() || getCookie("user_session");
  const jwt = authStorage.getJwt() || getCookie("jwt-token");
  if (!strict) return Boolean(userName && session);
  return Boolean(userName && session && jwt);
};

const getActiveUser = () => {
  return authStorage.getUserName() || getCookie("userName") || null;
};

const setActiveUser = (name) => {
  if (!name) return;
  setCookie("userName", name, { expires: 14 }); // 14 days
  ssSet("active_user_name", name);
};

const clearAuthArtifacts = () => {
  authStorage.clearAll();
  deleteCookie("userName");
  deleteCookie("jwt-token");
  deleteCookie("user_session");
  deleteCookie("role");
  deleteCookie("refresh-token");
  deleteCookie("email");
  deleteCookie("department_name");
  deleteCookie("login_timestamp");
  ssRemove("active_user_name");
  ssRemove("user_session");
  ssRemove("user_department");
  lsRemove("login_timestamp");
  ssRemove("id_token");
  lsRemove("auth_type");
  lsRemove("available_roles");
  clearMyDepartmentsCache();
};

// Broadcast channel constants
const CHANNEL_NAME = "auth_channel";
const FALLBACK_STORAGE_KEY = "auth_event"; // ephemeral single-use

const AuthContext = createContext({
  isAuthenticated: false,
  user: null, // { name, role, department }
  role: null,
  department: null,
  sessionId: null,
  loading: true,
  // API
  login: () => { },
  logout: () => { },
  forceReplaceLogin: () => { },
  syncFromCookies: () => { },
  // Helpers exposed (may be used externally e.g. LoginScreen / ProtectedRoute)
  hasAuthArtifacts,
  getActiveUser,
});

export const AuthProvider = ({ children }) => {
  const navigate = useNavigate();
  const { postData } = useFetch();

  // Tab identity
  const tabIdRef = useRef(`tab-${++tabIdCounter}-${Date.now()}`);
  const channelRef = useRef(null);
  const mountedRef = useRef(false);
  // Prevents concurrent/cascade logout calls (e.g. ProtectedRoute firing after SSO clearAuthArtifacts)
  const isLoggingOutRef = useRef(false);

  const [userState, setUserState] = useState(null); // { name, role, department }
  const [sessionId, setSessionId] = useState(null);
  const [loading, setLoading] = useState(true);

  const role = userState?.role || getCookie("role") || null;
  const department = userState?.department || getCookie("department_name") || ssGet("user_department") || null;

  // Hydration
  const syncFromCookies = useCallback(() => {
    const name = getActiveUser();
    const r = getCookie("role") || null;
    const dept = getCookie("department_name") || ssGet("user_department") || null;
    const sid = getCookie("user_session") || ssGet("user_session");
    // Restore session from core artifacts even when JWT is expired (refresh can recover)
    if (name && r && hasAuthArtifacts(false)) {
      setUserState({ name, role: r, department: dept });
    } else if (!hasAuthArtifacts(false)) {
      setUserState(null);
    }
    setSessionId(sid);
  }, []);

  useEffect(() => {
    syncFromCookies();

    // Clear orphaned session fragments left by expired logins (userName + session but no role)
    const name = getActiveUser();
    const session = authStorage.getSession() || getCookie("user_session");
    const role = getCookie("role");
    if (name && session && !role) {
      clearAuthArtifacts();
      setUserState(null);
      setSessionId(null);
    }

    setLoading(false);
  }, [syncFromCookies]);

  // Broadcast helper
  const broadcast = useCallback((type, payload = {}) => {
    const message = {
      type,
      userName: getActiveUser(),
      role: getCookie("role") || null,
      ts: Date.now(),
      sourceTabId: tabIdRef.current,
      ...payload,
    };
    try {
      if (channelRef.current) {
        channelRef.current.postMessage(message);
      }
    } catch (_) { }
    try {
      // Only store non-sensitive routing metadata in localStorage for the
      // cross-tab fallback. The receiving onStorage handler only reads
      // msg.type and msg.sourceTabId — it never reads userName or role.
      // Writing the full message would move sessionStorage-scoped identity
      // data into persistent localStorage (Fortify: Cross-Session Contamination).
      const fallbackMessage = {
        type: message.type,
        ts: Date.now(),
        sourceTabId: message.sourceTabId,
      };
      window.localStorage.setItem(FALLBACK_STORAGE_KEY, JSON.stringify(fallbackMessage));
      setTimeout(() => {
        try {
          window.localStorage.removeItem(FALLBACK_STORAGE_KEY);
        } catch (_) { }
      }, 50);
    } catch (_) { }
  }, []);

  const performLogoutStateClear = useCallback(() => {
    setUserState(null);
    setSessionId(null);
  }, []);

  const internalLogout = useCallback(
    (reason = "internal") => {
      clearAuthArtifacts();
      performLogoutStateClear();
      broadcast("LOGOUT", { reason });
      if (!isMsalLoginPending() && window.location.pathname !== "/login") {
        navigate("/login", { replace: true });
      }
    },
    [broadcast, navigate, performLogoutStateClear]
  );

  const login = useCallback(
    (payload) => {
      if (!payload || typeof payload !== "object") return;
      const { userName, role: newRole, refresh_token, department_name, email } = payload;
      const sessionCandidate = payload.user_session || payload.session_id || payload.sessionId || payload.session || null;

      if (userName) {
        setActiveUser(userName);
      }
      if (email) setCookie("email", email, { expires: 14 });
      if (newRole) setCookie("role", newRole, { expires: 14 });
      if (department_name) {
        setCookie("department_name", department_name, { expires: 14 });
        ssSet("user_department", department_name);
      }
      if (sessionCandidate) {
        setCookie("user_session", sessionCandidate, { expires: 14 });
        ssSet("user_session", sessionCandidate);
        setSessionId(sessionCandidate);
      }
      if (refresh_token) setCookie("refresh-token", refresh_token, { expires: 14 });

      // Update state after artifacts to align with validator
      setUserState({ name: userName, role: newRole, department: department_name });
      broadcast("LOGIN");
    },
    [broadcast]
  );

  const forceReplaceLogin = useCallback(
    (credentials) => {
      broadcast("REPLACE_SESSION", { targetUser: credentials?.userName });
      login(credentials);
    },
    [broadcast, login]
  );

  const logout = useCallback(
    async (reason = "manual", redirectPath = "/login") => {
      // Prevent concurrent/cascade calls — e.g. ProtectedRoute detecting missing
      // artifacts and calling logout again while SSO logout is already in progress.
      if (isLoggingOutRef.current) return;
      isLoggingOutRef.current = true;

      const authType = localStorage.getItem("auth_type"); // "sso" | "msal" | "local" | null
      const idToken = sessionStorage.getItem("id_token") || null;
      // Read JWT before clearing artifacts so we know if there is anything to invalidate.
      // Login flows persist JWT via authStorage.setJwt(); the cookie is only a legacy
      // fallback for older sessions. Read authStorage first, then cookie.
      const jwt = authStorage.getJwt() || Cookies.get("jwt-token") || null;

      // Block MSAL auto-login for any logout path (sign-out, session expiry, etc.)
      suppressMsalAutoLogin();

      if (authType === "msal" || msalInstance.getAllAccounts().length > 0) {
        // MSAL logout — clear cached MSAL accounts silently (no browser redirect).
        await clearMsalSession();
        clearAuthArtifacts();
        performLogoutStateClear();
      } else if (authType === "sso") {
        // SSO logout — call oauth logout endpoint, then redirect browser to Keycloak end-session URL
        try {
          const response = await postData(APIs.OAUTH_LOGOUT, {
            id_token: idToken || undefined,
          });
          clearAuthArtifacts();
          performLogoutStateClear();
          if (response && response.logout_url) {
            // Page navigates away — no need to reset the ref
            window.location.href = response.logout_url;
            return;
          }
        } catch (err) {
          // Non-critical — fall through to local cleanup
        }
      } else if (jwt) {
        // Local logout — only call backend if a JWT token actually exists.
        // Skipping when jwt is absent prevents 401 spam when this function is
        // called a second time after artifacts are already cleared.
        try {
          await postData(APIs.LOGOUT, {});
        } catch (err) {
          // Non-critical — clear state regardless
        }
      }

      clearAuthArtifacts();
      performLogoutStateClear();
      broadcast("LOGOUT", { reason });
      isLoggingOutRef.current = false;
      navigate(redirectPath, { replace: true });
    },
    [broadcast, navigate, performLogoutStateClear, postData]
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
            suppressMsalAutoLogin();
            performLogoutStateClear();
            // Ensure artifacts cleared locally (in case broadcast arrived first)
            clearAuthArtifacts();
            if (window.location.pathname !== "/login") navigate("/login", { replace: true });
            break;
          case "REPLACE_SESSION":
            performLogoutStateClear();
            clearAuthArtifacts();
            if (window.location.pathname !== "/login") navigate("/login", { replace: true });
            break;
          case "LOGIN":
            if (!hasAuthArtifacts()) return;
            if (!userState?.name) syncFromCookies();
            break;
          case "PING":
          default:
            break;
        }
      };
    } catch (_) { }

    const onStorage = (e) => {
      if (e.key !== FALLBACK_STORAGE_KEY || !e.newValue) return;
      try {
        const msg = JSON.parse(e.newValue);
        if (msg.sourceTabId === tabIdRef.current) return;
        channelRef.current?.onmessage?.({ data: msg });
      } catch (_) { }
    };
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener("storage", onStorage);
      try {
        channelRef.current && channelRef.current.close();
      } catch (_) { }
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

  // FIX #3: Track last good artifacts and add login grace period
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

      if (!strictArtifactsPresent) {
        // JWT cookie is missing but userName + user_session still exist.
        // Do NOT logout here — the axios 401 interceptor will attempt a
        // token refresh using email + user_session when the next API call
        // hits a 401.  If we called internalLogout now it would wipe
        // email/user_session/refresh-token and make refresh impossible.
        if (process.env.NODE_ENV === "development") {
          // eslint-disable-next-line no-console
          console.debug("[AuthContext] JWT cookie missing but core session intact — awaiting token refresh via interceptor.");
        }
        return;
      }

      lastGoodArtifactsRef.current = Date.now();

      if (userState?.name && activeUser && userState.name !== activeUser) {
        if (userState.name === "Guest") {
          syncFromCookies();
          return;
        }
        internalLogout("mismatch-active-user");
        return;
      }

      if (strictArtifactsPresent && !userState) syncFromCookies();
    };

    const debouncedValidate = () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(validate, 300);
    };

    // Debounce ALL event-driven validations, not just clicks.
    // 1500ms gives enough time for an in-flight token refresh to land before we validate.
    const debouncedFocusValidate = () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(validate, 1500);
    };

    // Use a single named handler for visibilitychange (fixes anonymous listener leak)
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") debouncedFocusValidate();
    };

    // Only use visibilitychange (covers tab switch reliably).
    // Removed duplicate "focus" listener — both fire on tab return, causing double validation.
    document.addEventListener("visibilitychange", onVisibilityChange);
    window.addEventListener("online", debouncedFocusValidate);
    document.addEventListener("click", debouncedValidate, true);

    const interval = setInterval(validate, 60000);

    return () => {
      clearTimeout(debounceTimer);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      window.removeEventListener("online", debouncedFocusValidate);
      document.removeEventListener("click", debouncedValidate, true);
      clearInterval(interval);
    };
  }, [internalLogout, syncFromCookies, userState]);

  const isAuthenticated = Boolean(userState?.name && hasAuthArtifacts(false) && getActiveUser() === userState.name);

  const value = useMemo(
    () => ({
      isAuthenticated,
      user: userState ? { name: userState.name, role: userState.role, department: userState.department } : null,
      userName: userState?.name || null,
      role,
      department,
      sessionId,
      loading,
      login,
      logout,
      internalLogout,
      forceReplaceLogin,
      syncFromCookies,
      hasAuthArtifacts: (strict) => hasAuthArtifacts(strict),
      getActiveUser,
    }),
    [isAuthenticated, userState, role, department, sessionId, loading, login, logout, internalLogout, forceReplaceLogin, syncFromCookies]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => useContext(AuthContext);
export { hasAuthArtifacts, getActiveUser, setActiveUser, clearAuthArtifacts };
export default AuthContext;
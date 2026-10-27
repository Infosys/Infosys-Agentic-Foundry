import { LogLevel, PublicClientApplication } from "@azure/msal-browser";

// All config is read from REACT_APP_* env vars at module load time.
// runtime window._env_ overlay is checked first to support Docker/k8s injected config.
const _env = (key) =>
  (typeof window !== "undefined" && window._env_ && window._env_[key]) ||
  process.env[key] ||
  "";

const MSAL_CLIENT_ID  = _env("REACT_APP_MSAL_CLIENT_ID");
const MSAL_AUTHORITY  = _env("REACT_APP_MSAL_AUTHORITY");
const MSAL_REDIRECT_URI = _env("REACT_APP_MSAL_REDIRECT_URI");
const MSAL_SCOPES_RAW = _env("REACT_APP_MSAL_SCOPES");

const getRedirectUri = () =>
  MSAL_REDIRECT_URI ||
  (typeof window !== "undefined" ? window.location.origin : "/");

const getPostLogoutRedirectUri = () => {
  const base =
    MSAL_REDIRECT_URI ||
    (typeof window !== "undefined" ? window.location.origin : "");
  return `${base}/login`;
};

const parseScopes = () => {
  if (MSAL_SCOPES_RAW) {
    return MSAL_SCOPES_RAW.split(",")
      .map((s) => s.trim())
      .filter(Boolean);
  }
  return ["User.Read", "openid", "profile", "email"];
};

export const msalConfig = {
  auth: {
    clientId: MSAL_CLIENT_ID,
    authority: MSAL_AUTHORITY,
    redirectUri: getRedirectUri(),
    postLogoutRedirectUri: getPostLogoutRedirectUri(),
    navigateToLoginRequestUrl: false,
  },
  cache: {
    cacheLocation: "sessionStorage",
    storeAuthStateInCookie: false,
  },
  system: {
    loggerOptions: {
      loggerCallback: (level, message, containsPii) => {
        if (containsPii || process.env.NODE_ENV === "production") return;
        if (level === LogLevel.Error) console.error(message);
        else if (level === LogLevel.Warning) console.warn(message);
      },
    },
  },
};

export const loginRequest = {
  scopes: parseScopes(),
};

export const logoutRequest = {
  account: undefined,
  postLogoutRedirectUri: getPostLogoutRedirectUri(),
};

export const msalInstance = new PublicClientApplication(msalConfig);

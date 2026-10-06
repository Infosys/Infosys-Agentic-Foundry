import { LogLevel, PublicClientApplication } from "@azure/msal-browser";
import {
  MSAL_CLIENT_ID,
  MSAL_AUTHORITY as MSAL_AUTHORITY_ENV,
  MSAL_REDIRECT_URI,
  MSAL_SCOPES,
} from "../constant";

const AUTHORITY = MSAL_AUTHORITY_ENV;

const getRedirectUri = () => {
  if (MSAL_REDIRECT_URI) return MSAL_REDIRECT_URI;
  return typeof window !== "undefined" ? window.location.origin : "/";
};

const getPostLogoutRedirectUri = () => {
  if (MSAL_REDIRECT_URI) return `${MSAL_REDIRECT_URI}/login`;
  return typeof window !== "undefined" ? `${window.location.origin}/login` : "/login";
};

const parseScopes = () => {
  if (MSAL_SCOPES) {
    return MSAL_SCOPES.split(",").map((scope) => scope.trim()).filter(Boolean);
  }
  return ["User.Read", "openid", "profile", "email"];
};

export const msalConfig = {
  auth: {
    clientId: MSAL_CLIENT_ID,
    authority: AUTHORITY,
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
        if (containsPii) return;
        if (process.env.NODE_ENV === "production") return;
        switch (level) {
          case LogLevel.Error:
            console.error(message);
            break;
          case LogLevel.Warning:
            console.warn(message);
            break;
          default:
            break;
        }
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

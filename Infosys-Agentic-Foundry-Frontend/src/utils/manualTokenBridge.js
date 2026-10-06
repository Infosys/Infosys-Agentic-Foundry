// MANUAL_TOKEN_MODE — temporary access token bypass
// To remove this feature: delete this file and remove its 3 import sites:
//   1. src/Hooks/useAxios.js       (import + 4-line if-block in performTokenRefresh)
//   2. src/components/Login/LoginScreen.jsx  (import + button + handler)
//   3. src/App.js                  (import + <ManualTokenModal />)
//
import { MANUAL_TOKEN_MODE_ENV } from "../constant";


const _readFlag = () => {
  const raw = (MANUAL_TOKEN_MODE_ENV || "").trim().toLowerCase();
  return raw === "true" || raw === "1" || raw === "yes";
};

export const MANUAL_TOKEN_MODE = _readFlag();

let _resolve = null;
let _reject = null;
const _listeners = new Set();

export const requestTokenFromUser = () =>
  new Promise((resolve, reject) => {
    _resolve = resolve;
    _reject = reject;
    _listeners.forEach((fn) => fn());
  });

export const resolveToken = (token) => {
  if (_resolve) {
    _resolve(token);
    _resolve = null;
    _reject = null;
  }
};

export const rejectToken = (reason) => {
  if (_reject) {
    _reject(reason instanceof Error ? reason : new Error(reason || "Token request rejected"));
    _resolve = null;
    _reject = null;
  }
};

export const subscribeToTokenRequest = (fn) => {
  _listeners.add(fn);
  return () => _listeners.delete(fn);
};

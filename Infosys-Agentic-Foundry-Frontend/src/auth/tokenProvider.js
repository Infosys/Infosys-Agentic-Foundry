import { msalInstance, loginRequest } from "./msalConfig";

/**
 * Returns a fresh MSAL access token. MSAL handles silent refresh automatically —
 * never cache this value yourself; always call this at request time.
 * Falls back to loginRedirect if the silent acquire fails (e.g. consent required).
 */
export async function getAccessToken() {
  const accounts = msalInstance.getAllAccounts();
  if (!accounts.length) {
    throw new Error("No MSAL account found. User is not signed in.");
  }

  try {
    const result = await msalInstance.acquireTokenSilent({
      ...loginRequest,
      account: accounts[0],
    });
    return result.accessToken;
  } catch (err) {
    // acquireTokenSilent throws when interaction is required (e.g. MFA, consent)
    await msalInstance.loginRedirect({ ...loginRequest, account: accounts[0] });
    throw err;
  }
}

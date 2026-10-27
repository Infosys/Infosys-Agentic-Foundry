import { msalInstance, loginRequest } from "./msalConfig";

/**
 * Returns a fresh MSAL access token for the currently signed-in account.
 *
 * MSAL handles silent token refresh automatically — never cache the returned
 * value; always call this at request time. Falls back to loginRedirect if
 * silent acquire fails (e.g. MFA challenge, consent required, session expired).
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
    // Interaction required (MFA, consent, session expired) — redirect to Azure AD
    await msalInstance.loginRedirect({ ...loginRequest, account: accounts[0] });
    throw err;
  }
}

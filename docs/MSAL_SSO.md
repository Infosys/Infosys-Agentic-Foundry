# Microsoft Authentication (MSAL / SSO) Integration

This document describes how Microsoft Authentication Library (MSAL) Single Sign-On (SSO)
is integrated into Agentic Pro UI, how to configure it, and how end users interact with it.

---

## Overview

Agentic Pro UI supports Microsoft Single Sign-On via **MSAL (Microsoft Authentication Library)
for browser** (`@azure/msal-browser` v5). When enabled, users can authenticate using their
organizational Microsoft 365 / Azure AD accounts instead of local credentials.

**Libraries used:**

| Package | Version |
|---|---|
| `@azure/msal-browser` | ^5.13.0 |
| `@azure/msal-react` | ^5.4.4 |

---

## How to Enable MSAL in the UI

**Step 1 — Register an Application in Azure AD**

1. Go to [Azure Portal → App Registrations](https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade).
2. Click **New registration**.
3. Enter a name (e.g., `Agentic Pro UI`).
4. Under **Supported account types**, select the appropriate option (usually *Single tenant* or *Accounts in this organizational directory only*).
5. Under **Redirect URI**, select **Single-page application (SPA)** and enter:
   ```
   https://<your-app-domain>/
   ```
   For local development:
   ```
   http://localhost:3003
   ```
6. Click **Register**.
7. From the **Overview** page, copy:
   - **Application (client) ID**
   - **Directory (tenant) ID**

**Step 2 — Configure Environment Variables**

Create a `.env` file at the project root (copy from `.env-example`) and set the following:

```env
# Required
REACT_APP_MSAL_CLIENT_ID="<your-azure-app-client-id>"
REACT_APP_MSAL_TENANT_ID="<your-azure-tenant-id>"

# Optional overrides (defaults are derived automatically)
# REACT_APP_MSAL_AUTHORITY="https://login.microsoftonline.com/<tenant-id>"
# REACT_APP_MSAL_REDIRECT_URI="https://<your-app-domain>"
# REACT_APP_MSAL_POST_LOGOUT_REDIRECT_URI="https://<your-app-domain>/login"
# REACT_APP_MSAL_SCOPES="User.Read,openid,profile,email"
```

| Variable | Required | Default | Description |
|---|---|---|---|
| `REACT_APP_MSAL_CLIENT_ID` | Yes | — | Azure AD Application (client) ID |
| `REACT_APP_MSAL_TENANT_ID` | Yes | — | Azure AD Directory (tenant) ID |
| `REACT_APP_MSAL_AUTHORITY` | No | `https://login.microsoftonline.com/<tenant-id>` | Authority URL for token endpoint |
| `REACT_APP_MSAL_REDIRECT_URI` | No | `window.location.origin` | URI Microsoft redirects to after login |
| `REACT_APP_MSAL_POST_LOGOUT_REDIRECT_URI` | No | `<origin>/login` | URI Microsoft redirects to after logout |
| `REACT_APP_MSAL_SCOPES` | No | `User.Read,openid,profile,email` | Comma-separated OAuth 2.0 scopes |

**Step 3 — Configure Redirect URIs in Azure**

In your Azure App Registration under **Authentication → Platform configurations → Single-page application**, ensure both URIs are listed:

- **Redirect URI**: `https://<your-app-domain>` (or `http://localhost:3003` for dev)
- **Front-channel logout URL** *(optional)*: `https://<your-app-domain>/login`

Enable the following under **Implicit grant and hybrid flows** if required:

- ID tokens
- Access tokens

**Step 4 — Ensure Backend User Provisioning is Configured**

The UI calls `GET /auth/me` with the MSAL access token after successful login to check user
status. The backend must be configured to accept Microsoft tokens and return one of the
following statuses:

| Status | UI Behaviour |
|---|---|
| `USER_EXISTS` | User is logged in and redirected to the home page |
| `NEEDS_DEPARTMENT_SELECTION` | User is redirected to `/select-department` |
| `PENDING_APPROVAL` | User is redirected to `/pending-approval` |
| `ACCOUNT_DEACTIVATED` | An error is displayed on the login page |

---

## How MSAL Authentication Works (Technical Flow)

**Initialization**

`src/index.js` initializes the MSAL instance and wraps the entire application with
`MsalProvider` before rendering:

```
msalInstance.initialize()
  └─> ReactDOM.render(<MsalProvider instance={msalInstance}> ... </MsalProvider>)
```

MSAL uses **sessionStorage** as its cache location (tokens do not persist across browser
restarts).

**Login Flow**

```
User clicks "Use single sign on"
  └─> LoginScreen.jsx → msalInstance.loginRedirect(loginRequest)
        └─> Browser redirects to login.microsoftonline.com
              └─> Microsoft authenticates the user
                    └─> Browser is redirected back to /
                          └─> MsalAuthCallback.jsx
                                ├─> msalInstance.handleRedirectPromise()
                                ├─> msalInstance.acquireTokenSilent()
                                ├─> GET /auth/me (backend user status check)
                                └─> Navigate to appropriate page
```

**Auto Sign-In for Cached Accounts**

`App.js` includes a `MsalEventHandler` component that runs on every page load (except the
login page). If a user's Microsoft account is already cached in sessionStorage, the handler
silently acquires a token and logs the user in without requiring them to click the SSO button
again.

This auto-sign-in is suppressed after a manual logout to prevent re-login loops.

**Token Refresh in API Calls**

The Axios request interceptor in `src/Hooks/useAxios.js` detects when the active session is
an MSAL session (`auth_type === "msal"` in localStorage) and automatically refreshes the
access token before each API call:

```
API Request
  └─> Interceptor detects auth_type = "msal"
        └─> msalInstance.acquireTokenSilent()
              └─> Sets Authorization: Bearer <token> header
```

If silent token acquisition fails (e.g., MFA required, session expired), the user is
redirected to Microsoft login.

**Logout Flow**

When a user logs out from an MSAL session:

1. The MSAL cache is cleared silently (no Microsoft logout page redirect).
2. An auto-login suppression flag is set to prevent re-login on the next page load.
3. All local auth artifacts (JWT, session ID, user data) are cleared.
4. The user is returned to the login page.

---

## Authentication Storage

After a successful MSAL login, the following items are stored in `localStorage`:

| Key | Value | Description |
|---|---|---|
| `jwt-token` | MSAL access token | Used as bearer token in all API calls |
| `user_session` | Generated session ID | Session tracking |
| `auth_type` | `"msal"` | Identifies the auth provider for logout and token refresh logic |
| `userName` | User's display name | Displayed in the UI |
| `email` | User's email address | Used for identification |
| `role` | User's role | Controls feature access |
| `department` | User's department | Set during department selection flow |
| `id_token` | `""` (empty) | Reserved for Keycloak SSO; empty for MSAL |

---

## How Users Use MSAL SSO from the UI

**Logging In with SSO**

1. Navigate to the application URL.
2. On the **Login** page, click the **"Use single sign on"** button.

   > The button label changes to *"Redirecting..."* while the redirect is in progress.

3. You are redirected to the Microsoft login page (`login.microsoftonline.com`).
4. Enter your organizational Microsoft 365 credentials and complete any MFA challenge.
5. Microsoft redirects you back to the application.
6. Depending on your account status:
   - **Existing user** — You are signed in and taken to the home page.
   - **New user (department required)** — You are taken to the department selection screen. Choose your department and submit.
   - **New user (pending approval)** — You are shown a *Pending Approval* screen. Wait for an administrator to approve your account.
   - **Deactivated account** — An error message is displayed. Contact your administrator.

**Automatic Sign-In**

If you have previously signed in with SSO and your Microsoft session is still active, the
application automatically signs you in the next time you open it — without needing to click
the SSO button.

**Logging Out**

Click your profile icon or the **Logout** button in the application. Your session is cleared
locally. Because MSAL SSO uses a silent logout (no Microsoft-side redirect), you remain
signed into your Microsoft account in the browser; only the application session is ended.

To prevent automatic re-login after logout, the application sets a suppression flag that
expires when you explicitly click **"Use single sign on"** again.

---

## Routing

| Route | Component | Purpose |
|---|---|---|
| `/login` | `LoginScreen` | Main login page with SSO button |
| `/` | `MsalAuthCallback` | Processes the Microsoft redirect response |
| `/select-department` | `SelectDepartment` | Department selection for new MSAL users |
| `/pending-approval` | `PendingApproval` | Approval waiting screen |

---

## Key Source Files

| File | Purpose |
|---|---|
| `src/auth/msalConfig.js` | MSAL `PublicClientApplication` configuration and instance |
| `src/auth/msalSessionUtils.js` | Helpers for auto-login suppression, session clearing |
| `src/auth/tokenProvider.js` | Manual token acquisition utility |
| `src/index.js` | MSAL initialization and `MsalProvider` wrapper |
| `src/App.js` | `MsalEventHandler` — handles cached-account auto sign-in |
| `src/components/Login/LoginScreen.jsx` | SSO login button and `loginRedirect` call |
| `src/components/Login/MsalAuthCallback.jsx` | Redirect handler, token exchange, user provisioning |
| `src/components/Login/SelectDepartment.jsx` | Post-login department selection |
| `src/components/Login/PendingApproval.jsx` | Pending approval UI |
| `src/context/AuthContext.jsx` | Logout logic for all auth types |
| `src/Hooks/useAxios.js` | Axios interceptor for automatic MSAL token refresh |

---

## Troubleshooting

| Symptom | Likely Cause | Resolution |
|---|---|---|
| Redirect loop after login | Redirect URI mismatch | Ensure `REACT_APP_MSAL_REDIRECT_URI` matches exactly what is registered in Azure |
| "AADSTS50011" error | Redirect URI not registered | Add the URI in Azure → App Registration → Authentication |
| Blank screen after SSO redirect | `REACT_APP_MSAL_CLIENT_ID` or `REACT_APP_MSAL_TENANT_ID` not set | Set both in `.env` and restart the dev server |
| Auto sign-in not working | Suppression flag active after logout | Click "Use single sign on" manually to clear the flag |
| `ACCOUNT_DEACTIVATED` error | Account disabled by admin | Contact your administrator |
| 401 errors on API calls | Token expired and silent refresh failed | Log out and log in again; ensure MSAL scopes include the API scope |
| Department selection not appearing | Backend returning `USER_EXISTS` for a new user | Verify backend `/auth/me` implementation |

---

## Important Notes

**Default Authentication Method**

When MSAL SSO is enabled, it is set as the **default authentication method** for the platform. Users are directed to Microsoft sign-in by default.

**Mutual Exclusion with Keycloak SSO**

Keycloak SSO and Microsoft (MSAL) SSO **cannot be enabled simultaneously**. A runtime guard prevents both from being active at the same time. If one is enabled, the other must be disabled before it can be activated.

**Unregistered User Access**

Unregistered Microsoft-authenticated users are granted agent chat access while their account is being provisioned. This allows users to begin interacting with agents immediately, even before an administrator has approved their registration request.

During **file upload and download**, the user's department is resolved automatically even when the user is not yet registered in a department, so file operations continue to work correctly for pending users.

**Default Role Assignment**

Microsoft-authenticated users and external users with no department mapping are automatically assigned a default role upon first login, ensuring they have baseline access to the platform.

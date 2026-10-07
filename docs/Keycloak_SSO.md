# Authentication

IAF uses JWT-based authentication enforced through a global `AuthenticationMiddleware` that runs on every request. Two authentication modes are supported — **Internal JWT** and **Keycloak SSO** — selected automatically based on the token presented.

---

## How It Works

Every incoming request passes through `AuthenticationMiddleware` before reaching any endpoint.

```
Incoming Request
      │
      ▼
Is this a public endpoint?  ──Yes──▶  Allow through (no auth check)
      │ No
      ▼
Is this an OPTIONS request? ──Yes──▶  Allow through (CORS preflight)
      │ No
      ▼
Extract Bearer token from Authorization header
      │
      ▼
Run token validation (Path 1 → Path 2)
      │
      ├─ Valid ──▶ Set user context (email, role, department) → Continue
      │
      └─ Invalid ──▶ 401 Unauthorized
```

---

## Token Validation Paths

Validation is attempted in order. If Path 1 fails, Path 2 is tried.

**Path 1 — Internal JWT (HS256)**

Used when the user logged in directly through IAF's own `/auth/login` endpoint.

- Token is a signed HS256 JWT issued by IAF itself
- Validated using `AUTH_JWT_SECRET` (minimum 32 characters, enforced at startup)
- Claims verified: **signature**, **expiry (`exp`)**
- User email, role, and department are read directly from the token payload
- Access token lifetime is configurable via `AUTH_ACCESS_TOKEN_EXPIRE_SECONDS` (default: 15 minutes)
- Optional refresh token support via `AUTH_ENABLE_REFRESH_TOKENS`

**Token payload structure:**

| Claim | Description |
|---|---|
| `mail_id` | User's email address |
| `user_name` | Display name |
| `role` | User role (`User`, `Admin`, `SuperAdmin`) |
| `department_name` | User's department |
| `exp` | Expiry timestamp |

---

**Path 2 — Keycloak SSO (RS256)**

Used when `KEYCLOAK_ENABLED=true` and the token is a Keycloak-issued RS256 JWT. This path handles SSO logins via the Authorization Code Flow.

**Token verification steps:**

1. Read `kid` (key ID) from the token header without verifying
2. Fetch the matching RSA public key from Keycloak's JWKS endpoint:
   ```
   {KEYCLOAK_SERVER_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs
   ```
3. Verify the **RS256 signature** using the fetched public key
4. Verify **issuer (`iss`)** matches `{KEYCLOAK_SERVER_URL}/realms/{KEYCLOAK_REALM}`
5. Verify **expiry (`exp`)** and **issued-at (`iat`)**
6. Extract user email from `email` or `preferred_username` claim
7. Map Keycloak realm roles to IAF roles (`admin` → `Admin`, default → `User`)

**Key rotation** is handled automatically — the JWKS cache refreshes every hour and invalidates on unknown `kid`.

!!! note
    Audience (`aud`) verification is currently skipped in this path to support tokens issued for multiple client IDs within the same realm.

---

## Authentication Flow (Keycloak SSO)

```
User / Application
      │
      ▼
1. Initiate SSO Login
   GET /auth/oauth/login
   ──▶ Redirects to Keycloak login page

      │
      ▼
2. User authenticates with Keycloak
   (username/password, MFA if configured)

      │
      ▼
3. Keycloak redirects back to IAF
   GET /auth/oauth/callback?code=...&state=...

      │
      ▼
4. IAF exchanges authorization code for tokens
   ──▶ Keycloak returns: access_token, id_token, refresh_token
   ──▶ Nonce verified from id_token for CSRF protection
   ──▶ User provisioned in IAF database (JIT provisioning)

      │
      ▼
5. IAF returns access_token to frontend
   (via POST form or redirect, depending on OAUTH_TOKEN_DELIVERY_METHOD)

      │
      ▼
6. All subsequent API calls:
   Authorization: Bearer <access_token>
   ──▶ Validated via Path 2 (RS256 JWKS verification)
```

---

## Public Endpoints

The following endpoints are accessible without a Bearer token:

| Endpoint | Purpose |
|---|---|
| `POST /auth/login` | Internal login |
| `POST /auth/register` | User registration |
| `GET /auth/guest-login` | Guest access |
| `GET /auth/oauth/login` | Initiate Keycloak SSO |
| `GET /auth/oauth/callback` | Keycloak callback |
| `GET /health` | Health check |
| `GET /utility/get/version` | Version info |
| `GET /docs` | Swagger UI |

---

## User Context

After successful validation, the following context is set for every request and is accessible throughout the request lifecycle:

| Context Variable | Source |
|---|---|
| `current_user_email` | Extracted from token claims |
| `current_user_role` | Mapped from token claims |
| `current_user_department` | Extracted from token claims |
| `current_request_headers` | Full request headers |

---

## Roles

| Role | Description |
|---|---|
| `User` | Standard access — can use assigned agents |
| `Admin` | Department-level management |
| `SuperAdmin` | Full platform access across all departments |

---

## Configuration

**Internal JWT**

| Environment Variable | Description | Default |
|---|---|---|
| `AUTH_JWT_SECRET` | Secret key for signing tokens (min 32 chars) | Required |
| `AUTH_JWT_ALGORITHM` | Signing algorithm | `HS256` |
| `AUTH_ACCESS_TOKEN_EXPIRE_SECONDS` | Access token lifetime in seconds | `900` (15 min) |
| `AUTH_ENABLE_REFRESH_TOKENS` | Enable refresh token rotation | `false` |
| `AUTH_REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token lifetime in days | `14` |

**Keycloak SSO**

| Environment Variable | Description |
|---|---|
| `KEYCLOAK_ENABLED` | Enable Keycloak SSO (`true` / `false`) |
| `KEYCLOAK_SERVER_URL` | Base URL of the Keycloak server |
| `KEYCLOAK_REALM` | Keycloak realm name |
| `KEYCLOAK_CLIENT_ID` | IAF's client ID registered in Keycloak |
| `KEYCLOAK_CLIENT_SECRET` | IAF's client secret |
| `KEYCLOAK_REDIRECT_URI` | OAuth callback URL registered in Keycloak |

!!! warning
    The server **will not start** if `AUTH_JWT_SECRET` is missing, less than 32 characters, or uses the development default `CHANGE_ME_DEV_ONLY`.


## Important Notes

**Mutual Exclusion with Microsoft (MSAL) SSO**

Keycloak SSO and Microsoft (MSAL) SSO **cannot be enabled simultaneously**. A runtime guard prevents both from being active at the same time. If you need to switch SSO providers, disable the current provider before enabling the other.

**SSO Direct Entry**

When Keycloak SSO is enabled, users are redirected directly to the Keycloak login page, bypassing the platform's manual login screen. After successful authentication, users land directly on the platform home page.

**Email Notifications**

Email notifications are dispatched when a new user registers via SSO and when their account is approved by an administrator.

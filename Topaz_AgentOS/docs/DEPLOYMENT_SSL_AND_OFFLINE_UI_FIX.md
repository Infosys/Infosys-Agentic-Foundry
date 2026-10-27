# Deployment Fix — Outbound SSL/Proxy Trust + Offline UI

> Hand-off runbook for deploying AgentOS as a container on the Infosys corporate
> network (Zscaler proxy) in an air-gapped / CDN-blocked environment.
>
> Covers two independent problems that were breaking the containerized deployment:
>
> 1. **Azure OpenAI calls fail** with `SSL: CERTIFICATE_VERIFY_FAILED`.
> 2. **UI renders unstyled** because Tailwind/fonts are loaded from a public CDN.

---

## 1. Outbound SSL / Proxy Trust

### Symptom

```
httpcore.proxy | start_tls ... server_hostname='sohan-...openai.azure.com'
start_tls.failed ... [SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate
```
The proxy identifies itself as `Proxy-Agent: Zscaler/6.2`.

### Root cause

Outbound traffic splits into two paths with **different** trust requirements:

| Target | Route | Cert signed by | Needs in trust store |
|---|---|---|---|
| Internal model (self-hosted vLLM/Gemma), e.g. `blriipminfa100.ad.infosys.com:8004` | **DIRECT** (host is in `NO_PROXY`) | Infosys internal CA chain | Infosys internal chain |
| Azure OpenAI, `*.openai.azure.com` | **through Zscaler proxy** (TLS interception) | **Zscaler / Infosys-PXY root** | **Infosys-PXY root** |

Zscaler re-signs the Azure certificate with its own root CA (`Infosys-PXY`). The
container's default trust store (`certifi`) does not contain that CA, so
verification fails.

Two aggravating factors that were fixed:

1. **One shared SSL knob.** `model_registry.py` used a single `OPENAI_SSL_VERIFY`
   for *both* Azure and the internal model. Pointing Azure at the internal-only
   bundle guarantees `CERTIFICATE_VERIFY_FAILED`.
2. **Global cert in the image.** The Dockerfile runtime stage baked
   `ENV SSL_CERT_FILE=/etc/ssl/certs/infy-fullchain.pem`. `fullchain.pem` is the
   **inbound** TLS server chain — forcing it as the global outbound trust store
   breaks every public HTTPS client.

> **Windows note:** an earlier Windows-host fix simply *cleared* the cert env vars
> so Azure fell back to the Windows Certificate Store (which already trusts
> `Infosys-PXY`). **That does not work in a Linux container** — there is no
> Windows store. The proxy CA must be supplied explicitly (below).

### Code changes (already in the repo — commit `ea98e69`+)

`IAF-Agent-Skills/agentos_model/model_registry.py` — SSL trust is now scoped
**per connection**:

- `_get_public_ssl_verify()` → used by **Azure** (public, via proxy). Reads
  `PUBLIC_CA_BUNDLE`. Deliberately never falls back to the internal bundle.
- `_get_internal_ssl_verify()` → used by the **internal** OpenAI-compatible model
  (Gemma/vLLM). Reads `INTERNAL_CA_BUNDLE`, then `OPENAI_SSL_VERIFY` (back-compat).

`IAF-Agent-Skills/iaf_agent_skills/memory.py` — Azure embeddings now prefer
`PUBLIC_CA_BUNDLE`.

`Dockerfile` — runtime stage no longer bakes a global `SSL_CERT_FILE`. (The
**builder** stage keeps it — that is build-time only, for pip through the proxy,
and never ships to the runtime image.)

### Certificate files

Placed in the `./certs` folder (mounted read-only at `/certs`):

| File | Purpose | Used by |
|---|---|---|
| `fullchain.pem` + `privatekey.pem` | **Inbound** HTTPS (UI over TLS) | `uvicorn --ssl-certfile/--ssl-keyfile` |
| `combined-ca-bundle.pem` | **Outbound, internal/direct** (Gemma) — Infosys internal chain | `INTERNAL_CA_BUNDLE` |
| `public-ca-bundle.pem` | **Outbound, public via proxy** (Azure) — public roots **+ Infosys-PXY** | `PUBLIC_CA_BUNDLE` |

Create `public-ca-bundle.pem` (nothing shipped today contains the proxy CA):

```bash
# public roots from certifi
python -c "import certifi,shutil; shutil.copyfile(certifi.where(),'public-roots.pem')"
# append the Zscaler / Infosys-PXY root CA (obtain from infra/security)
cat public-roots.pem infosys-pxy.pem > public-ca-bundle.pem
# place it next to the other certs so it mounts at /certs/public-ca-bundle.pem
```

### `.env` settings

```bash
# Never set a global outbound bundle — trust is per-connection
SSL_CERT_FILE=
REQUESTS_CA_BUNDLE=

# Internal, direct model (Gemma/vLLM) — Infosys internal chain
INTERNAL_CA_BUNDLE=/certs/combined-ca-bundle.pem

# Public model via the corporate proxy (Azure) — MUST contain Infosys-PXY
PUBLIC_CA_BUNDLE=/certs/public-ca-bundle.pem

# Corporate proxy (Azure is public → via proxy; internal hosts stay in NO_PROXY)
HTTPS_PROXY=http://blrproxy.ad.infosys.com:443
HTTP_PROXY=http://blrproxy.ad.infosys.com:443
```

### Verify (from inside the running container)

```bash
# Azure through the proxy — must succeed with the public bundle
podman exec iaf-agentos curl -v --proxy "$HTTPS_PROXY" \
  --cacert /certs/public-ca-bundle.pem \
  https://sohan-mbtd9z9j-eastus2.openai.azure.com/

# Gemma direct — must succeed with the internal bundle
podman exec iaf-agentos curl -v --cacert /certs/combined-ca-bundle.pem \
  https://blriipminfa100.ad.infosys.com:8004/v1/models

# Confirm the per-connection code is baked into the image
podman run --rm iaf-agentos:<tag> \
  python -c "import agentos_model.model_registry as m; print(hasattr(m,'_get_public_ssl_verify'))"
# -> True
```

> **Rule going forward:** never set `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` globally
> to a server chain. Scope the CA per connection: `PUBLIC_CA_BUNDLE` for public
> (proxy-intercepted) endpoints, `INTERNAL_CA_BUNDLE` for direct internal ones.
> Do **not** disable verification (`OPENAI_SSL_VERIFY=false`) — it is an insecure
> workaround for a MITM proxy and will fail security review.

---

## 2. Offline UI (air-gapped / CDN-blocked)

### Symptom

UI loads unstyled; console shows CSP violations for `cdn.tailwindcss.com` and
font hosts, plus `Uncaught ReferenceError: tailwind is not defined`.

### Root cause

The HTML pages load Tailwind from `https://cdn.tailwindcss.com` and fonts from
`assets.vercel.com`. In an air-gapped environment the browser cannot reach those
hosts, so styling never loads. (This is a browser-side reachability problem —
independent of the SSL issue above.)

### Fix — vendor the assets locally

1. **Download the Tailwind v3 Play CDN build** (the pages use the v3
   `tailwind.config = {...}` API, so v3 is required — not v4):

   ```
   https://cdn.tailwindcss.com/3.4.16
   ```
   Save as `IAF-Agent-Studio/static/vendor/tailwind.js` (overwrite the v4 file).

2. **Repoint every page** from the CDN to the local copy:

   ```html
   <!-- from -->
   <script src="https://cdn.tailwindcss.com"></script>
   <!-- to -->
   <script src="/static/vendor/tailwind.js"></script>
   ```

   Files that reference the CDN: `index.html`, `dashboard_v2.html`,
   `skill-builder-v2.html`, `skill-creator.html`, `studio.html`, `finops.html`,
   `optimization.html`, `rl_workbench.html`, `rl_capture.html`, `twin.html`,
   `login.html`, `index_v2_chatgpt.html`, `index_v3_refined.html`.

3. **Vendor the fonts** (Geist / Geist Mono `.woff2`) into
   `static/vendor/fonts/` and point the `@font-face` / `<link>` at
   `/static/vendor/fonts/...`.

4. **Tighten the CSP** in `IAF-Agent-Studio/auth/middleware.py` once everything is
   same-origin (drop the CDN and wildcard; `unsafe-eval` stays — Alpine.js and the
   Tailwind Play JIT require it):

   ```python
   "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
   "style-src 'self' 'unsafe-inline'; "
   "font-src 'self' data:; "
   ```

---

## 3. Build → Tag → Push

The runtime image is built from this repo and pushed to JFrog.

```bash
# 1. Build (use --no-cache after any Dockerfile / token change)
podman build -f Dockerfile -t iaf-agentos:<tag> . --no-cache
#    Override the proxy only if it changed:
#    --build-arg HTTPS_PROXY=http://blrproxy.ad.infosys.com:443

# 2. Tag for the JFrog registry
podman tag localhost/iaf-agentos:<tag> \
  infyartifactory.jfrog.io/infyagenticrepo/iaf-agentos:<tag>

# 3. Log in and push
podman login infyartifactory.jfrog.io
podman push infyartifactory.jfrog.io/infyagenticrepo/iaf-agentos:<tag>
```

Example (as used):

```bash
podman tag localhost/iaf-agentos:3.0.8 \
  infyartifactory.jfrog.io/infyagenticrepo/iaf-agentos:3.0.9
podman push infyartifactory.jfrog.io/infyagenticrepo/iaf-agentos:3.0.9
```

> **Keep the tag consistent.** Build, tag, push, and the `image:` line in
> `docker-compose.yml` must all reference the **same** tag, or you will deploy a
> stale image. Bump the version on every rebuild.

### Deploy

```bash
# Update docker-compose.yml -> image: infyartifactory.jfrog.io/infyagenticrepo/iaf-agentos:<tag>
podman compose up -d --force-recreate
```

---

## 4. Pre-flight checklist for the deploying team

- [ ] Repo is at commit `ea98e69` or later (per-connection SSL code present).
- [ ] Dockerfile runtime stage has **no** global `ENV SSL_CERT_FILE` (builder stage keeps it).
- [ ] `./certs` contains `fullchain.pem`, `privatekey.pem`, `combined-ca-bundle.pem`, and `public-ca-bundle.pem` (public roots + Infosys-PXY).
- [ ] `.env` sets `INTERNAL_CA_BUNDLE`, `PUBLIC_CA_BUNDLE`, proxy vars; clears global `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE`.
- [ ] Tailwind (+ fonts) vendored under `static/vendor/`; HTML repointed; CSP tightened (only if targeting air-gapped browsers).
- [ ] Image built, tagged, pushed with a **new** version; `docker-compose.yml` `image:` matches.
- [ ] Post-deploy: both `curl` verifications succeed inside the container; UI renders styled.

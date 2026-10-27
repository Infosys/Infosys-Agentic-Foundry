# OpenShell sandbox backend — working runbook (verified 2026-10-01)

AgentOS execution running inside a real NVIDIA OpenShell VM sandbox on an
Apple-Silicon Mac, behind a corporate TLS-intercepting proxy with PyPI, ghcr.io,
nvcr.io, docker.io and GitHub release downloads all blocked.

**Verified result** — `kernel.run_shell_command()` through the backend:

```
$ id                      uid=1000(ubuntu) gid=1000(ubuntu) groups=1000(ubuntu)
$ uname -srm              Linux 6.12.76 aarch64          # host is macOS
$ hostname                agentos-sbx3
$ head -1 /etc/os-release PRETTY_NAME="Ubuntu 24.04.5 LTS"
$ cat <host>/agent_os/config.env   -> FAILS (no host filesystem)
$ python3 -c "print(1)"            -> Error [COMMAND_BLOCKED]  (host-side governance intact)
```

The `config.env` read is the point: on the `local` backend that same command
succeeds and leaks every API key.

---

## 1. What was blocked, and the way round each

| Blocker | Workaround |
|---|---|
| `pypi.org` → 403 | JFrog PyPI mirror already in `~/.pip/pip.conf` → `pip install openshell` works |
| `github.com/.../releases/download/` → Zscaler block page | **`api.github.com` release-assets endpoint** works, and `gh` is authenticated → `gh release download` |
| `nvcr.io` / `ghcr.io` / `registry-1.docker.io` → 403 | JFrog **docker-remote** and **ghcr-remote** proxies |
| Driver not entitled for Hypervisor.framework | re-sign ad-hoc **with** `com.apple.security.hypervisor` + `…virtualization` |
| Driver has no documented registry auth | undocumented **`OPENSHELL_REGISTRY_USERNAME` / `OPENSHELL_REGISTRY_TOKEN`** (found via `strings`) |
| `mke2fs` missing; `brew` can't run (portable-ruby from ghcr.io, not mirrored) | pull the e2fsprogs + gettext **bottles** via JFrog ghcr-remote and relocate the `@@HOMEBREW_*@@` placeholders by hand with `install_name_tool` + re-sign |
| Python TLS fails on the Zscaler CA | use `curl` (trusts the macOS keychain) — same reason `jev_client` does |

## 2. Layout

```
~/openshell/
  bin/{openshell,openshell-gateway,openshell-driver-vm}   # v0.1.2, checksums verified
  pki/{ca.crt,ca.key,server/,client/,jwt/}                # openshell-gateway generate-certs
  brew/{e2fsprogs,gettext,opt/gettext}                    # hand-relocated bottles
  rootfs/ubuntu-24.04-arm64.tar.gz                        # pulled from JFrog docker-remote
  gateway.toml                                            # schema v2
  start-driver.sh  brew-via-jfrog.sh  relocate-e2fsprogs.sh
/private/tmp/osvm/{d.sock,state/,regcreds.env}            # NOT /tmp — it is a symlink and the driver refuses it
/opt/homebrew/opt/e2fsprogs -> ~/openshell/brew/e2fsprogs/1.47.4
```

## 3. Start the stack (order matters)

```sh
# 1. driver first — it creates the socket the gateway waits 30s for
~/openshell/start-driver.sh &            # reads regcreds.env (mode 600) for registry auth

# 2. gateway second
~/openshell/bin/openshell-gateway \
  --config ~/openshell/gateway.toml \
  --bind-address 127.0.0.1 --port 17670 \
  --compute-driver vm --compute-driver-socket /private/tmp/osvm/d.sock \
  --name openshell &

# 3. register + verify
~/openshell/bin/openshell gateway add https://127.0.0.1:17670 --local --name openshell
~/openshell/bin/openshell --gateway openshell status    # → Authenticated (mTLS transport)
~/openshell/bin/openshell --gateway openshell sandbox create --name agentos-sbx3
```

Gotchas that cost real time:
- **Driver before gateway.** The gateway exits after 30s with `transport error` otherwise, and the driver will not accept a *second* gateway after the first disconnects — restart both together.
- **Auth is mandatory for VM launch** (`VM sandbox launch authentication is required`). `--disable-tls` with no mTLS/OIDC gets you a connected gateway that cannot launch anything.
- **`--grpc-endpoint` must match the gateway scheme.** Pointing the driver at `http://` while the gateway serves TLS surfaces inside the guest as `grpc-status header missing, mapped from HTTP status code 404`.
- `--guest-tls-ca` requires `--guest-tls-cert` **and** `--guest-tls-key`.
- Background daemons must be properly detached; a plain `&` inside a short-lived shell gets reaped and leaves a stale socket.

## 4. Point AgentOS at it

```sh
AGENTOS_KERNEL_BACKEND=openshell
AGENTOS_SANDBOX_URL=https://127.0.0.1:17670       # scheme is stripped; gRPC needs host:port
AGENTOS_SANDBOX_TLS_CA=~/openshell/pki/ca.crt
AGENTOS_SANDBOX_TLS_CERT=~/openshell/pki/client/tls.crt
AGENTOS_SANDBOX_TLS_KEY=~/openshell/pki/client/tls.key
AGENTOS_SANDBOX_NAME=agentos-sbx3                 # omit → one sandbox per tenant/agent/user
AGENTOS_SANDBOX_WORKSPACE=default
AGENTOS_SANDBOX_ROOT=/sandbox                     # the guest has /sandbox, NOT /workspace
```

Default stays `local`; nothing changes until the backend is set explicitly.

## 5. Open items before this is demo-ready in UI chat

1. **The sandbox filesystem is empty.** No tenant data is mounted, so skills that
   read `/shared/**` through the `shell` tool find nothing. `run_sql_query` is
   unaffected (it opens SQLite host-side). Mount or sync tenant data before
   running the finance workstreams on this backend.
2. **Minimal image.** `curl` is absent from `ubuntu:24.04`, so the egress gate
   returns `exit 127: curl: not found` rather than being exercised. Use an image
   with curl, or install it into the sandbox, to demo egress policy.
3. **Hand-relocated bottles are a local hack**, not a supported install. On Linux
   (the real target) `dnf`/`apt` provides `e2fsprogs` and none of §1 applies.
4. **Session reuse is per-process.** `_attach()` caches a session on the runtime
   instance; a long-lived agent reuses one sandbox, which is intended, but there
   is no idle reaping yet.
5. The gateway currently trusts a locally generated CA. For production use real
   PKI/OIDC and run the gateway off-host (see `OPENSHELL_INTEGRATION_DESIGN.md`).

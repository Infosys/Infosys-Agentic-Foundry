"""
Observers — runtime abstraction.

`ObserverRuntime(ABC)` turns an ObserverSpec into a running Headlong observer.
The compile step (spec -> identity files) is shared; the two concrete runtimes
differ only in HOW the mind is launched and how scope is enforced:

  DevRuntime        — Mac / no Docker. Runs Headlong with HEADLONG_UNSANDBOXED=1.
                      Scope is PROMPT-ONLY (not enforced) — prints a loud banner.
  ContainerRuntime  — Linux + Docker. Emits a `docker run` with read-only mounts
                      per watch scope + `--network none` — the real fence.

`create_observer_runtime()` selects the impl from OBSERVERS_RUNTIME, mirroring
`create_queue_manager()`. The ABC leaves room for a future K8sRuntime with no
caller changes.

SAFETY: start() only actually spawns/executes when OBSERVERS_AUTOSTART=1. By
default it provisions files and returns the exact launch command, so wiring can
be validated without spawning long-lived processes.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional

from observers.models import Access, ObserverSpec, RuntimeMode
from shared.config import HEADLONG_APP_DIR, OBSERVERS_RUNTIME

logger = logging.getLogger(__name__)

_AUTOSTART = os.getenv("OBSERVERS_AUTOSTART", "false").lower() == "true"
_DOCKER_IMAGE = os.getenv("OBSERVERS_DOCKER_IMAGE", "ubuntu:latest")
# Where the Console's gateway + key live, injected into the mind/sidecar env.
_GATEWAY_URL = os.getenv("OBSERVERS_GATEWAY_URL", "http://127.0.0.1:8082")
_LOCAL_BIN = str(Path.home() / ".local" / "bin")


def _identities_root() -> Path:
    return Path(HEADLONG_APP_DIR) / ".identities"


def _identity_dir(spec: ObserverSpec) -> Path:
    return _identities_root() / spec.name


def _scope_statement(spec: ObserverSpec) -> str:
    """The soft (prompt) scope statement. In dev this is the ONLY constraint;
    in container it merely mirrors the hard mount boundary."""
    if not spec.watch:
        return "You have no configured data sources."
    lines = ["You may ONLY read from these sources — never anything else:"]
    for w in spec.watch:
        loc = w.path or w.dsn or w.url or "?"
        lines.append(f"  - {w.type.value}: {loc} ({w.access.value})")
    lines.append(
        "You cannot write, modify, or delete anything. To make anything happen "
        "in the world, call the agentos_act skill — a human governs every action."
    )
    return "\n".join(lines)


def _build_identity_prompt(spec: ObserverSpec) -> str:
    return (
        f"You are {spec.name}, a persistent observer agent.\n\n"
        f"Focus: {spec.focus or 'watch your scope and surface what matters.'}\n"
        f"Vibe: {spec.vibe or 'methodical, cautious, escalates when unsure.'}\n\n"
        f"{_scope_statement(spec)}\n"
    )


def _build_goal_memories(spec: ObserverSpec) -> List[str]:
    """One goal memory per trigger, so the monolith loop keeps them in view."""
    memories: List[str] = []
    for i, t in enumerate(spec.triggers):
        cond = t.pattern or f"{t.field} {t.op} {t.value}"
        memories.append(
            "---\n"
            f"type: goal\n"
            f"created: observer-provision\n"
            "---\n"
            f"When you observe [{cond}], call agentos_act with skill "
            f"'{t.skill}'. Approval: {t.approval.value}.\n"
        )
    return memories


# Cheap default model for background observers; override via spec.model.
_DEFAULT_MIND_MODEL = "gpt-5-nano"


def _resolve_model(spec: ObserverSpec) -> str:
    """The model the mind should think with: the spec's explicit model, else the
    cheap fleet default. MUST resolve to a provider-backed model — Headlong's own
    built-in default is claude-opus-4-7, which has no key in this env, so an
    unpinned observer would otherwise spawn a mind that dies rc=1 every wakeup.
    """
    return spec.model or _DEFAULT_MIND_MODEL


def _build_env(spec: ObserverSpec, unsandboxed: bool) -> str:
    lines = []
    model = _resolve_model(spec)
    lines.append(f"SHELLM_MODEL={model}")
    # The llm Azure bridge routes by AZURE_OPENAI_DEPLOYMENT, so make the deployment follow the model.
    if model.startswith(("gpt-", "gpt5", "o1", "o3", "o4")):
        lines.append(f"AZURE_OPENAI_DEPLOYMENT={model}")
    if spec.llm_api_url:
        lines.append(f"LLM_API_URL={spec.llm_api_url}")
    if unsandboxed:
        lines += ["HEADLONG_UNSANDBOXED=1", "SHELLM_REQUIRE_DOCKER=0"]
    else:
        # inside the outer container fence; inner shellm runs local mode.
        lines += ["HEADLONG_UNSANDBOXED=0", "SHELLM_REQUIRE_DOCKER=0"]
    # Gateway coordinates for the agentos_act skill (sourced by activate).
    gateway = os.getenv("OBSERVERS_GATEWAY_URL", "http://127.0.0.1:8082")
    api_key = os.getenv("OBSERVERS_API_KEY", "")
    lines.append(f"OBSERVERS_GATEWAY_URL={gateway}")
    if api_key:
        lines.append(f"OBSERVERS_API_KEY={api_key}")
    return "\n".join(lines) + "\n"


def _provision_identity(spec: ObserverSpec, unsandboxed: bool) -> Path:
    """Create/refresh the Headlong identity files for this observer.

    Uses the Headlong `identity new` CLI when available; otherwise creates a
    minimal identity dir so dev-mode wiring still works without Headlong.
    """
    idir = _identity_dir(spec)
    # Rebuild stub identity dirs (left by a failed `identity new`) so observers self-heal.
    is_stub = idir.exists() and not (idir / "activate").exists()
    if is_stub:
        logger.warning("Observer '%s' identity is a stub (no activate) — rebuilding", spec.name)
        shutil.rmtree(idir, ignore_errors=True)
    if not idir.exists():
        # shutil.which uses the server PATH, which usually lacks ~/.local/bin; check the Headlong bin dirs.
        cli = shutil.which("identity")
        if not cli:
            for cand in (Path(_LOCAL_BIN) / "identity",
                         Path(HEADLONG_APP_DIR) / "tools" / "identity"):
                if cand.exists():
                    cli = str(cand)
                    break
        created = False
        if cli:
            try:
                subprocess.run(
                    [cli, "new", spec.name],
                    cwd=HEADLONG_APP_DIR, check=True,
                    capture_output=True, text=True, timeout=60,
                    env=_headlong_env(),   # PATH incl ~/.local/bin for identity's sub-tools
                )
                created = True
            except Exception as exc:
                logger.warning("`identity new %s` failed (%s) — minimal scaffold",
                               spec.name, exc)
        if not created and not idir.exists():
            # Minimal scaffold (dev fallback — wiring holds, but the mind can't run).
            for sub in ("memories", "skills", "trajectories", "run/logs"):
                (idir / sub).mkdir(parents=True, exist_ok=True)
            (idir / "info.txt").write_text(f"name={spec.name}\n")

    # Overwrite the parts we own (idempotent).
    (idir / "memories").mkdir(parents=True, exist_ok=True)
    (idir / "core_identity_prompt.md").write_text(_build_identity_prompt(spec))
    for i, mem in enumerate(_build_goal_memories(spec)):
        (idir / "memories" / f"goal_{i:02d}.md").write_text(mem)
    # _build_env embeds OBSERVERS_API_KEY; persist it owner-only (0600) so a local
    # user who can read the Headlong identity dir can't steal the gateway key.
    _env_path = idir / ".env"
    _env_path.write_text(_build_env(spec, unsandboxed))
    try:
        _env_path.chmod(0o600)
    except OSError:
        pass  # best-effort (e.g. Windows/!POSIX); never block provisioning
    # Pin think_model in info.txt; thinkers ignore SHELLM_MODEL and fall back to an unconfigured default.
    _upsert_info_field(idir / "info.txt", "think_model", _resolve_model(spec))
    _install_agentos_act_skill(idir)
    # chat/.chatrc so the Console can message the live mind (like the 'ada' identity).
    chatdir = idir / "chat"
    chatdir.mkdir(parents=True, exist_ok=True)
    chatrc = chatdir / ".chatrc"
    if not chatrc.exists():
        chatrc.write_text("default_send_from=operator\n")
    logger.info("Provisioned observer identity: %s", idir)
    return idir


def _install_agentos_act_skill(idir: Path) -> None:
    """Symlink (or copy) the packaged agentos_act Headlong skill into the
    identity's skills/ dir so the agent can call the governed gateway."""
    src = Path(__file__).resolve().parent / "headlong_skills" / "agentos_act"
    if not src.exists():
        return
    dst = idir / "skills" / "agentos_act"
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        if dst.is_symlink() or dst.exists():
            return
        dst.symlink_to(src)
    except OSError:  # filesystems without symlink support — copy instead
        shutil.copytree(src, dst)


def _latest_trajectory(spec: ObserverSpec) -> Path | None:
    tdir = _identity_dir(spec) / "trajectories"
    if not tdir.exists():
        return None
    files = sorted(tdir.glob("*/trajectory.jsonl"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def _run_dir(spec: ObserverSpec) -> Path:
    d = _identity_dir(spec) / "run"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _console_state_path(spec: ObserverSpec) -> Path:
    return _run_dir(spec) / "console.json"


def _read_console_state(spec: ObserverSpec) -> dict:
    p = _console_state_path(spec)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _write_console_state(spec: ObserverSpec, state: dict) -> None:
    _console_state_path(spec).write_text(json.dumps(state))


def _pid_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def _headlong_env(unsandboxed: bool = True) -> dict:
    """Environment for headlong CLI + sidecar: PATH incl ~/.local/bin, gateway coords."""
    env = dict(os.environ)
    env["PATH"] = _LOCAL_BIN + os.pathsep + env.get("PATH", "")
    if unsandboxed:
        env["HEADLONG_UNSANDBOXED"] = "1"
    env.setdefault("OBSERVERS_GATEWAY_URL", _GATEWAY_URL)
    if os.getenv("OBSERVERS_API_KEY"):
        env["OBSERVERS_API_KEY"] = os.environ["OBSERVERS_API_KEY"]
    return env


def _headlong_shell(idir: Path, command: str, unsandboxed: bool = True, timeout: int = 60) -> subprocess.CompletedProcess:
    """Run a command inside the identity's activated Headlong env (sources ./activate)."""
    full = f'cd "{idir}" && source ./activate >/dev/null 2>&1 && {command}'
    return subprocess.run(["bash", "-lc", full], env=_headlong_env(unsandboxed),
                          capture_output=True, text=True, timeout=timeout)


def _upsert_info_field(info_path: Path, key: str, value: str) -> None:
    """Set `key=value` in a Headlong identity info.txt (its model-of-record),
    replacing any existing line or appending. Creates the file if missing."""
    lines = []
    if info_path.exists():
        lines = [ln for ln in info_path.read_text().splitlines()
                 if not ln.startswith(f"{key}=")]
    lines.append(f"{key}={value}")
    info_path.write_text("\n".join(lines) + "\n")


def _preflight_llm(idir: Path, timeout: int = 30):
    """Health-check the mind's `llm` using the identity's configured model.

    Returns (ok, msg). Never raises — an unreachable/unbacked model (e.g. a
    claude-* model with no ANTHROPIC_API_KEY) must be SURFACED, not fatal, so a
    dead mind doesn't masquerade as healthy. Runs the same activated env the
    monolith uses, so it exercises the real SHELLM_MODEL."""
    try:
        r = _headlong_shell(idir, "printf 'ping' | llm >/dev/null", timeout=timeout)
        if r.returncode == 0:
            return True, "ok"
        tail = (r.stderr or r.stdout or "").strip().splitlines()
        return False, (tail[-1][:200] if tail else f"llm exited rc={r.returncode}")
    except Exception as exc:
        return False, str(exc)[:200]


def _sidecar_pids(observer: str) -> List[int]:
    """Every running sidecar PID for this EXACT observer.

    Matches the process argv `... -m observers.sidecar <observer>` (observer is
    the final arg), so it catches orphans left by repeated starts — not just the
    last-recorded pid. Empty on any error (best-effort)."""
    pids: List[int] = []
    try:
        r = subprocess.run(["pgrep", "-f", "observers.sidecar"],
                           capture_output=True, text=True, timeout=10)
    except Exception:
        return pids
    for tok in r.stdout.split():
        try:
            pid = int(tok)
        except ValueError:
            continue
        try:
            cmd = subprocess.run(["ps", "-o", "command=", "-p", str(pid)],
                                 capture_output=True, text=True, timeout=5).stdout.strip()
        except Exception:
            continue
        # Exact match: it's the sidecar module and the final arg is this observer.
        if "observers.sidecar" in cmd and cmd.split()[-1:] == [observer]:
            pids.append(pid)
    return pids


def _kill_sidecars(observer: str, exclude: Optional[int] = None) -> int:
    """SIGTERM (then SIGKILL if stubborn) all sidecars for `observer`.

    `exclude` skips a pid (e.g. one we just started). Returns the count TERM'd.
    Fixes the orphan bug where a re-start left the previous sidecar running and
    stop() only killed the last-recorded pid."""
    targets = [p for p in _sidecar_pids(observer) if p != exclude]
    for pid in targets:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    if targets:
        time.sleep(0.5)
        for pid in _sidecar_pids(observer):          # anything that ignored TERM
            if pid == exclude:
                continue
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    return len(targets)


def _start_sidecar(spec: ObserverSpec) -> Optional[int]:
    """Launch the deterministic trigger sidecar as a background process.

    Idempotent: any sidecar already running for this observer (e.g. from a prior
    start that wasn't stopped) is killed first, so we never orphan one."""
    _kill_sidecars(spec.name)
    log = _run_dir(spec) / "sidecar.log"
    env = _headlong_env()
    env["OBSERVERS_POLL_SECONDS"] = env.get("OBSERVERS_POLL_SECONDS", "1")
    try:
        with open(log, "ab") as fh:
            proc = subprocess.Popen(
                [sys.executable, "-m", "observers.sidecar", spec.name],
                stdout=fh, stderr=fh, env=env, start_new_session=True,
            )
        return proc.pid
    except Exception as exc:
        logger.warning("sidecar start failed for '%s': %s", spec.name, exc)
        return None


class ObserverRuntime(ABC):
    @abstractmethod
    def provision(self, spec: ObserverSpec) -> Path:
        ...

    @abstractmethod
    def start(self, spec: ObserverSpec) -> Dict:
        ...

    @abstractmethod
    def stop(self, spec: ObserverSpec) -> Dict:
        ...

    def status(self, spec: ObserverSpec) -> Dict:
        """Real running state: was it started via the console, and is the sidecar
        alive. last_activity comes from the trajectory mtime."""
        st = _read_console_state(spec)
        sidecar_alive = _pid_alive(st.get("sidecar_pid"))
        running = bool(st.get("started")) and (sidecar_alive or st.get("mode") == "container")
        traj = _latest_trajectory(spec)
        llm_ok = st.get("llm_ok", None)
        return {
            "running": running,
            "started": bool(st.get("started")),
            "sidecar_alive": sidecar_alive,
            "mode": st.get("mode"),
            "thinkers_ok": st.get("thinkers_ok"),
            "llm_ok": llm_ok,
            "llm_msg": st.get("llm_msg", ""),
            "model": st.get("model", ""),
            # A mind is only healthy if it's running AND its last LLM preflight passed.
            "healthy": bool(running and (llm_ok is not False)),
            "last_activity": traj.stat().st_mtime if traj else None,
            "trajectory": str(traj) if traj else None,
        }


class DevRuntime(ObserverRuntime):
    """Mac / no-Docker. Scope is NOT enforced — only the prompt guides it."""

    def provision(self, spec: ObserverSpec) -> Path:
        return _provision_identity(spec, unsandboxed=True)

    def start(self, spec: ObserverSpec) -> Dict:
        idir = self.provision(spec)
        logger.warning("Observer '%s' starting in DEV mode — scope NOT enforced", spec.name)
        # 1. Start the Headlong mind (dispatcher + monolith + responder).
        thinkers_ok, thinkers_msg = True, "started"
        try:
            r = _headlong_shell(idir, "thinkers start monolith responder", timeout=45)
            thinkers_ok = r.returncode == 0
            thinkers_msg = (r.stdout or r.stderr or "").strip()[-300:]
        except Exception as exc:
            thinkers_ok, thinkers_msg = False, str(exc)
            logger.warning("thinkers start failed for '%s': %s", spec.name, exc)
        # 2. Start the deterministic sidecar.
        sidecar_pid = _start_sidecar(spec)
        # 2b. Preflight the mind's LLM so an unbacked model (no provider key) is
        #     surfaced immediately rather than dying rc=1 on every wakeup unseen.
        llm_ok, llm_msg = _preflight_llm(idir)
        if not llm_ok:
            logger.warning("Observer '%s' LLM preflight FAILED (model=%s): %s",
                           spec.name, spec.model or "(llm default)", llm_msg)
        # 3. Record console state for status()/stop().
        _write_console_state(spec, {
            "started": True, "mode": "dev", "enforced": False,
            "sidecar_pid": sidecar_pid, "started_at": time.time(),
            "thinkers_ok": thinkers_ok,
            "llm_ok": llm_ok, "llm_msg": llm_msg, "model": spec.model or "",
        })
        return {"mode": "dev", "enforced": False, "running": True,
                "thinkers_ok": thinkers_ok, "thinkers_msg": thinkers_msg,
                "llm_ok": llm_ok, "llm_msg": llm_msg,
                "sidecar_pid": sidecar_pid}

    def stop(self, spec: ObserverSpec) -> Dict:
        idir = _identity_dir(spec)
        st = _read_console_state(spec)
        # 1. Stop the mind.
        thinkers_msg = "not running"
        if idir.exists():
            try:
                r = _headlong_shell(idir, "thinkers stop --force", timeout=30)
                thinkers_msg = (r.stdout or r.stderr or "").strip()[-200:]
            except Exception as exc:
                thinkers_msg = str(exc)
        # 2. Kill the sidecar(s) — ALL of them for this observer, not just the
        #    last-recorded pid, so orphans from earlier starts are cleaned up too.
        killed = _kill_sidecars(spec.name)
        # Belt-and-suspenders: also honour the recorded pid if pgrep missed it.
        pid = st.get("sidecar_pid")
        if _pid_alive(pid):
            try:
                os.kill(int(pid), signal.SIGTERM)
                killed += 1
            except Exception as exc:
                logger.warning("sidecar kill failed: %s", exc)
        _write_console_state(spec, {"started": False, "mode": "dev",
                                    "stopped_at": time.time()})
        return {"mode": "dev", "running": False,
                "thinkers_msg": thinkers_msg, "sidecars_killed": killed}


class ContainerRuntime(ObserverRuntime):
    """Linux + Docker. The outer container is the deterministic fence."""

    def provision(self, spec: ObserverSpec) -> Path:
        return _provision_identity(spec, unsandboxed=False)

    def _docker_command(self, spec: ObserverSpec) -> List[str]:
        # KNOWN LIMITATION: provisioning-only; no mind runs and --network none blocks gateway egress.
        idir = _identity_dir(spec)
        cmd = [
            "docker", "run", "-d",
            "--name", f"observer-{spec.name}",
            "--network", "none",                 # egress off (Headlong has no such knob)
            "-v", f"{idir}:{idir}",              # identity home (rw)
        ]
        for w in spec.watch:
            if w.type.value == "folder" and w.path:
                ro = ":ro" if w.access == Access.ro else ""
                cmd += ["-v", f"{w.path}:{w.path}{ro}"]   # read-only watch mount = the fence
        cmd += [_DOCKER_IMAGE, "sleep", "infinity"]
        return cmd

    def start(self, spec: ObserverSpec) -> Dict:
        self.provision(spec)
        cmd = self._docker_command(spec)
        logger.info("Observer '%s' container command: %s", spec.name, " ".join(cmd))
        started = False
        if _AUTOSTART and shutil.which("docker"):
            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=120)
                started = True
            except Exception as exc:
                logger.error("Container start failed for '%s': %s", spec.name, exc)
        _write_console_state(spec, {"started": started, "mode": "container",
                                    "enforced": True, "started_at": time.time()})
        return {"mode": "container", "enforced": True, "command": " ".join(cmd),
                "started": started, "running": started}

    def stop(self, spec: ObserverSpec) -> Dict:
        stopped = False
        if shutil.which("docker"):
            try:
                subprocess.run(["docker", "rm", "-f", f"observer-{spec.name}"],
                               capture_output=True, text=True, timeout=60)
                stopped = True
            except Exception as exc:
                logger.warning("container stop failed for '%s': %s", spec.name, exc)
        _write_console_state(spec, {"started": False, "mode": "container",
                                    "stopped_at": time.time()})
        return {"mode": "container", "running": False, "stopped": stopped}


def create_observer_runtime(mode: str | None = None) -> ObserverRuntime:
    """Pick the runtime impl. Precedence: explicit arg > OBSERVERS_RUNTIME env (default 'dev').

    KNOWN LIMITATION (deferred; observers feature-flagged off): the router calls this
    WITHOUT a mode, so ObserverSpec.runtime_mode is not honored — every spec uses the
    process-wide OBSERVERS_RUNTIME. A production pass should pass spec.runtime_mode here
    so a per-observer `container` setting actually sandboxes it.
    """
    chosen = (mode or OBSERVERS_RUNTIME or "dev").lower()
    if chosen == RuntimeMode.container.value:
        return ContainerRuntime()
    return DevRuntime()

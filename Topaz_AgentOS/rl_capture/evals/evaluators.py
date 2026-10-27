"""Versioned evaluator contracts and subprocess-backed Python execution."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

import yaml

# `resource` is Unix-only; _limits_preexec already no-ops on non-POSIX.
if os.name == "posix":
    import resource
else:
    resource = None  # type: ignore[assignment]

from rl_capture.evals.registry import validate_eval_id
from rl_capture.evals.rubric import extract_output_text

MAX_STDOUT_BYTES = 256_000
DEFAULT_TIMEOUT_MS = 5_000
DEFAULT_MEMORY_MB = 256

# Prevent child processes from popping a console window on Windows, where the
# server runs under console-less pythonw.exe. Evaluates to 0 (no-op) elsewhere.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def list_evaluators(registry_dir: Path) -> list[dict[str, Any]]:
    """List normalized evaluator manifests from an explicit registry directory."""
    root = Path(registry_dir)
    root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("*/manifest.yaml")):
        try:
            rows.append(load_evaluator_manifest(root, path.parent.name))
        except Exception as exc:  # noqa: BLE001 - surface broken manifests without hiding healthy ones
            rows.append({
                "id": path.parent.name,
                "enabled": False,
                "error": str(exc),
                "source_file": str(path.relative_to(root)),
            })
    return rows


def load_evaluator_manifest(registry_dir: Path, evaluator_id: str) -> dict[str, Any]:
    evaluator_id = validate_eval_id(evaluator_id)
    evaluator_dir = Path(registry_dir) / evaluator_id
    manifest_path = evaluator_dir / "manifest.yaml"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Evaluator '{evaluator_id}' not found")
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("Evaluator manifest must be a mapping")
    normalized = _normalize_manifest(raw, fallback_id=evaluator_id, evaluator_dir=evaluator_dir)
    normalized["source_file"] = str(manifest_path.relative_to(Path(registry_dir)))
    return normalized


def build_evaluator_input(
    *,
    suite: dict[str, Any],
    case: dict[str, Any],
    candidate: dict[str, Any],
    assertion_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the stable JSON payload passed to tenant evaluator plug-ins."""
    target = suite.get("target") or {}
    return {
        "contract_version": "agentpro_eval_evaluator_v1",
        "suite": {
            "id": suite.get("id"),
            "name": suite.get("name"),
            "target": target,
            "rubric": suite.get("rubric") or {},
            "thresholds": suite.get("thresholds") or {},
        },
        "case": case,
        "candidate": {
            "output_text": extract_output_text(candidate),
            "raw": candidate,
            "metadata": candidate.get("metadata") or {},
            "tool_calls": candidate.get("tool_calls") or [],
            "observations": candidate.get("observations") or [],
        },
        "expected": case.get("expected"),
        "assertions": assertion_result or {},
        "metadata": {
            "case_id": case.get("id"),
            "suite_id": suite.get("id"),
            "target_type": target.get("type"),
            "target_name": target.get("name") or target.get("role") or target.get("skill"),
        },
    }


def run_python_evaluator(
    *,
    registry_dir: Path,
    evaluator_id: str,
    payload: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run an allowlisted Python evaluator in a fresh subprocess."""
    manifest = load_evaluator_manifest(registry_dir, evaluator_id)
    if not manifest.get("enabled", True):
        raise ValueError(f"Evaluator '{evaluator_id}' is disabled")
    if manifest.get("type") != "python":
        raise ValueError(f"Evaluator '{evaluator_id}' is not a python evaluator")

    entrypoint = Path(manifest["entrypoint_abs"])
    timeout_ms = int((config or {}).get("timeout_ms") or manifest.get("timeout_ms") or DEFAULT_TIMEOUT_MS)
    memory_mb = int((config or {}).get("memory_mb") or manifest.get("memory_mb") or DEFAULT_MEMORY_MB)
    request = {
        "manifest": {
            "id": manifest["id"],
            "version": manifest.get("version") or "",
            "function": manifest["function"],
        },
        "config": {**(manifest.get("config") or {}), **(config or {})},
        "payload": payload,
    }
    code = _worker_code(entrypoint, manifest["function"])
    started = time.time()
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-c", code],
            input=json.dumps(request, ensure_ascii=False),
            text=True,
            capture_output=True,
            cwd=str(entrypoint.parent),
            env=_sanitized_env(),
            timeout=max(timeout_ms / 1000.0, 0.1),
            preexec_fn=_limits_preexec(memory_mb),
            creationflags=_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        return _error_result(manifest, f"timeout after {timeout_ms}ms", started)

    stdout = (completed.stdout or "")[:MAX_STDOUT_BYTES]
    stderr = (completed.stderr or "")[-4096:]
    if completed.returncode != 0:
        return _error_result(manifest, f"subprocess exited {completed.returncode}: {stderr.strip()}", started)
    try:
        raw = json.loads(stdout or "{}")
    except json.JSONDecodeError as exc:
        return _error_result(manifest, f"invalid evaluator JSON: {exc}", started)
    return normalize_evaluator_result(raw, manifest=manifest, started=started)


def normalize_evaluator_result(raw: dict[str, Any], *, manifest: dict[str, Any], started: float | None = None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {"score": -1.0, "verdict": "fail", "reasons": ["evaluator returned non-object JSON"]}
    score = _clamp_score(raw.get("reward", raw.get("score", 0.0)))
    verdict = str(raw.get("verdict") or _verdict_for_score(score)).strip().lower()
    if verdict not in {"pass", "partial", "fail"}:
        verdict = _verdict_for_score(score)
    confidence = _clamp_unit(raw.get("confidence", 0.8))
    duration_ms = int((time.time() - started) * 1000) if started else int(raw.get("duration_ms") or 0)
    return {
        "score": score,
        "reward": _clamp_score(raw.get("reward", score)),
        "verdict": verdict,
        "confidence": confidence,
        "rubric": raw.get("rubric") or f"python:{manifest['id']}:{manifest.get('version') or 'v1'}",
        "components": raw.get("components") if isinstance(raw.get("components"), dict) else {},
        "reasons": [str(item) for item in (raw.get("reasons") or [])],
        "evidence": raw.get("evidence") if isinstance(raw.get("evidence"), list) else [],
        "metadata": raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
        "evaluator": {
            "type": "python",
            "id": manifest["id"],
            "version": manifest.get("version") or "",
            "entrypoint": manifest.get("entrypoint") or "",
            "function": manifest.get("function") or "",
        },
        "duration_ms": duration_ms,
    }


def _normalize_manifest(raw: dict[str, Any], *, fallback_id: str, evaluator_dir: Path) -> dict[str, Any]:
    evaluator_id = validate_eval_id(raw.get("id") or fallback_id)
    evaluator_type = str(raw.get("type") or "python").strip().lower()
    if evaluator_type != "python":
        raise ValueError("Only python evaluator manifests are supported")
    entrypoint = str(raw.get("entrypoint") or "evaluator.py").strip()
    if entrypoint.startswith("/") or ".." in Path(entrypoint).parts:
        raise ValueError("Evaluator entrypoint must be a relative path inside the evaluator directory")
    entrypoint_abs = (evaluator_dir / entrypoint).resolve()
    try:
        entrypoint_abs.relative_to(evaluator_dir.resolve())
    except ValueError as exc:
        raise ValueError("Evaluator entrypoint escaped evaluator directory") from exc
    if not entrypoint_abs.exists():
        raise FileNotFoundError(f"Evaluator entrypoint not found: {entrypoint}")
    function = str(raw.get("function") or "score_case").strip()
    if not function.isidentifier():
        raise ValueError("Evaluator function must be a valid identifier")
    config = raw.get("config") or {}
    if not isinstance(config, dict):
        raise ValueError("Evaluator config must be a mapping")
    return {
        "id": evaluator_id,
        "name": str(raw.get("name") or evaluator_id),
        "description": str(raw.get("description") or ""),
        "type": evaluator_type,
        "version": str(raw.get("version") or "v1"),
        "enabled": bool(raw.get("enabled", True)),
        "entrypoint": entrypoint,
        "entrypoint_abs": str(entrypoint_abs),
        "function": function,
        "timeout_ms": int(raw.get("timeout_ms") or DEFAULT_TIMEOUT_MS),
        "memory_mb": int(raw.get("memory_mb") or DEFAULT_MEMORY_MB),
        "config": dict(config),
        "tags": [str(tag) for tag in (raw.get("tags") or [])],
    }


def _worker_code(entrypoint: Path, function: str) -> str:
    return textwrap.dedent(
        f"""
        import importlib.util
        import json
        import sys
        path = {str(entrypoint)!r}
        function_name = {function!r}
        request = json.loads(sys.stdin.read() or "{{}}")
        spec = importlib.util.spec_from_file_location("tenant_eval_module", path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        fn = getattr(module, function_name)
        result = fn(request.get("payload") or {{}}, request.get("config") or {{}})
        sys.stdout.write(json.dumps(result, ensure_ascii=False, default=str))
        """
    )


def _limits_preexec(memory_mb: int):
    def set_limits() -> None:
        memory_bytes = max(int(memory_mb or DEFAULT_MEMORY_MB), 32) * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        except Exception:
            pass
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
        except Exception:
            pass
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
        except Exception:
            pass

    return set_limits if os.name == "posix" else None


def _sanitized_env() -> dict[str, str]:
    keep = {
        "LANG": os.getenv("LANG", "C.UTF-8"),
        "LC_ALL": os.getenv("LC_ALL", "C.UTF-8"),
        "PYTHONIOENCODING": "utf-8",
    }
    return {key: value for key, value in keep.items() if value}


def _error_result(manifest: dict[str, Any], message: str, started: float) -> dict[str, Any]:
    return {
        "score": -1.0,
        "reward": -1.0,
        "verdict": "fail",
        "confidence": 1.0,
        "rubric": f"python:{manifest.get('id')}:error",
        "components": {},
        "reasons": [message],
        "evidence": [],
        "metadata": {"error": message},
        "evaluator": {
            "type": "python",
            "id": manifest.get("id") or "",
            "version": manifest.get("version") or "",
            "entrypoint": manifest.get("entrypoint") or "",
            "function": manifest.get("function") or "",
        },
        "duration_ms": int((time.time() - started) * 1000),
        "error": message,
    }


def _clamp_score(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = 0.0
    return round(max(-1.0, min(1.0, parsed)), 3)


def _clamp_unit(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = 0.0
    return round(max(0.0, min(1.0, parsed)), 3)


def _verdict_for_score(score: float) -> str:
    return "pass" if score >= 0.3 else ("fail" if score <= -0.3 else "partial")

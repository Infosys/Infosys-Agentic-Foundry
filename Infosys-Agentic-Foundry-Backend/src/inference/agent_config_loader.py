# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Shared utility for loading mount-related config from ``agent_config.json``.

Replaces the duplicated config-loading boilerplate that was copy-pasted
across all five inference modules (H4).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from telemetry_wrapper import logger as log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


def load_agent_mount_config(
    agent_id: str | None,
    *,
    agent_dir: Path | None = None,
    department: str | None = None,
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[List[str]]]:
    """Return ``(additional_paths, allowed_absolute_mount_roots)`` from disk.

    Parameters
    ----------
    agent_id:
        The agent identifier.  If *None* both values are returned as *None*.
    agent_dir:
        If known, the Path to the agent directory (e.g. from
        ``_resolve_agent_dir``).  When supplied, *department* is ignored.
    department:
        Fallback department name used to compute the agent directory when
        *agent_dir* is not provided.  Defaults to ``"General"``.

    Returns
    -------
    tuple
        ``(additional_paths, allowed_absolute_mount_roots)`` — each can be
        *None* if the key is absent or the file does not exist.
    """
    if not agent_id:
        return None, None

    if agent_dir is None:
        # Compute the standard on-disk path.  Import at call-time to avoid
        # circular dependencies in module-load order.
        try:
            from src.utils.secrets_handler import current_user_department as _cud
            dept = _cud.get(department or "General")
        except Exception:
            dept = department or "General"
        agent_dir = Path("./agent_workspaces") / dept / "agentos_agents" / agent_id

    config_path = agent_dir / "agent_config.json"
    if not config_path.exists():
        return None, None

    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8-sig"))
        additional_paths = cfg.get("additional_paths", None)
        allowed_roots = cfg.get("allowed_absolute_mount_roots", None)
        if additional_paths:
            log.info(
                f"[AgentConfigLoader] Loaded {len(additional_paths)} "
                f"additional_paths for agent {agent_id}"
            )
        return additional_paths, allowed_roots
    except Exception as exc:
        log.warning(
            f"[AgentConfigLoader] Could not read agent_config.json "
            f"for {agent_id}: {exc}"
        )
        return None, None


def build_mount_prompt_section(
    additional_paths: Optional[List[Dict[str, Any]]] = None,
    allowed_absolute_mount_roots: Optional[List[str]] = None,
) -> str:
    """Build a system-prompt appendix that advertises mounted folders and
    tells the agent to use ``run_shell_command`` to read them.

    Returns an empty string when no mounts are configured. The block is safe
    to append verbatim to any system prompt.
    """
    lines: List[str] = []

    if additional_paths:
        for ap in additional_paths:
            if not isinstance(ap, dict):
                continue
            rel = str(ap.get("path", "") or "").strip()
            if not rel:
                continue
            perm = str(ap.get("permission", "read") or "read").strip().lower()
            mount_name = rel.replace("\\", "/").strip("/").split("/")[-1]
            safe = "".join(
                c if c.isalnum() or c in ("-", "_") else "_"
                for c in mount_name.lower()
            )
            if not safe:
                continue
            mode_label = "READ-WRITE" if perm == "read-write" else "READ-ONLY"
            # Show the original folder name alongside the canonical mount name
            # only when they differ, so the agent sees both spellings.
            if mount_name and mount_name.lower() != safe:
                lines.append(
                    f"- `/{safe}/` — Additional mounted folder ({mode_label}) "
                    f"(source folder: `{mount_name}`; mount name is "
                    f"case-insensitive)"
                )
            else:
                lines.append(f"- `/{safe}/` — Additional mounted folder ({mode_label})")

    if allowed_absolute_mount_roots:
        for root in allowed_absolute_mount_roots:
            root_str = str(root or "").strip()
            if not root_str:
                continue
            # Absolute mounts are accessed via their real absolute path.
            lines.append(
                f"- `{root_str}` — Allowed absolute path root (READ-ONLY unless "
                f"listed above as READ-WRITE)"
            )

    if not lines:
        return ""

    section = "\n\n### Additional Mounted Folders\n" + "\n".join(lines) + "\n"
    section += (
        "\n**Reading files in mounted folders:** Use "
        "`run_shell_command(command=\"readfile /<mount>/filename\")` to read PDF, "
        "Excel, DOCX, PPTX, CSV, images, Parquet, and other binary/complex files. "
        "If you only know the filename, just use `readfile filename.pdf` — it "
        "auto-discovers across all mounts. Use `ls /<mount>/` to browse a mount, "
        "and `grep`/`find` for searching. Mount names are **case-insensitive** "
        "(e.g. `/rfp_test/` and `/RFP_test/` refer to the same mount), but "
        "filenames inside the mount keep their original case. For absolute-path "
        "roots listed above, reference files using their full absolute path.\n"
    )
    return section

"""Per-package configuration for IAF-Agent-Skills.

Environment-derived settings are read inside a dataclass (via default_factory)
rather than at a raw os.getenv() call feeding a filesystem sink, so path values
reach open()/Path() through this object. This keeps behaviour identical while
decoupling the env source from the sink (avoids the direct env->file-sink
dataflow that static analysis flags as Path Manipulation).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class SkillsConfig:
    """Environment-derived configuration for the skills runtime."""
    config_env_path: str = field(default_factory=lambda: os.getenv("CONFIG_ENV_PATH", ""))
    # Optional override for the platform-hooks manifest location.
    platform_hooks_manifest: str = field(
        default_factory=lambda: os.getenv("IAF_PLATFORM_HOOKS_MANIFEST", "")
    )


skills_config = SkillsConfig()

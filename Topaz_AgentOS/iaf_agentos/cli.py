"""Command-line interface for IAF AgentOS."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from iaf_agentos import __version__
from iaf_agentos.config import (
    ApplicationConfig,
    app_config,
    resolve_data_root,
    sanitize_data_root,
    sanitize_execution_mode,
    sanitize_model_name,
    sanitize_skill_name,
    sanitize_tenant_id,
)
from iaf_agentos.factory import _ensure_data_root

logger = logging.getLogger(__name__)


_cli_logger = logging.getLogger("iaf_agentos.cli")


def _emit_stdout(text: str) -> None:
    """Write user-facing output via logging."""
    _cli_logger.info("%s", text)


def _emit_stderr(text: str) -> None:
    """Write user-facing errors via logging."""
    _cli_logger.warning("%s", text)


def _resolve_cli_config(
    *,
    data_root: str | None = None,
    tenant: str | None = None,
    model: str | None = None,
) -> ApplicationConfig:
    """Build a CLI-scoped config from sanitised args and defaults."""
    return ApplicationConfig(
        data_root=sanitize_data_root(data_root or app_config.data_root),
        tenant_id=sanitize_tenant_id(tenant or app_config.tenant_id),
        model=sanitize_model_name(model or app_config.model),
    )


def cmd_init(args: argparse.Namespace) -> int:
    """Scaffold enterprise_root structure."""
    cfg = _resolve_cli_config(data_root=args.data_root, tenant=args.tenant)
    root = _ensure_data_root(cfg.data_root, cfg.tenant_id)
    skills_dir = root / "tenants" / cfg.tenant_id / "skills"
    contexts_dir = root / "tenants" / cfg.tenant_id / "shared" / "contexts"

    _emit_stdout("Initialized enterprise_root.")
    _emit_stdout(f" Tenant: {cfg.tenant_id}")
    _emit_stdout(f" Skills: {skills_dir}")
    _emit_stdout(f" Contexts: {contexts_dir}")
    _emit_stdout("")
    _emit_stdout("Next steps:")
    _emit_stdout(f" 1. Add skills: agentos skill create my_skill --tenant {cfg.tenant_id}")
    _emit_stdout(f" 2. Run agent: agentos run 'Hello' --tenant {cfg.tenant_id}")
    _emit_stdout(" 3. Start server: agentos serve")
    logger.debug("Initialized data root at %s", root)
    return 0


def cmd_skill_list(args: argparse.Namespace) -> int:
    """List registered skills."""
    import yaml

    cfg = _resolve_cli_config(data_root=args.data_root, tenant=args.tenant)
    root = resolve_data_root(cfg.data_root)
    skills_path = root / "tenants" / cfg.tenant_id / "skills" / "_index.yaml"

    if not skills_path.exists():
        _emit_stderr("No skills index found.")
        logger.debug("Missing skills index at %s", skills_path)
        return 1

    with open(skills_path, encoding="utf-8") as handle:
        index = yaml.safe_load(handle) or {}

    skills = index.get("skills", {})
    _emit_stdout(f"Skills for tenant '{cfg.tenant_id}' ({len(skills)} registered):")
    _emit_stdout(f"{'Name':<30s} {'Description':<60s}")
    _emit_stdout("-" * 90)
    for name, meta in sorted(skills.items()):
        description = ""
        if isinstance(meta, dict):
            description = str(meta.get("description", ""))
        _emit_stdout(f"{name:<30s} {description[:60]:<60s}")
    return 0


def cmd_skill_create(args: argparse.Namespace) -> int:
    """Scaffold a new skill."""
    cfg = _resolve_cli_config(data_root=args.data_root, tenant=args.tenant)
    skill_name = sanitize_skill_name(args.name)
    mode = sanitize_execution_mode(args.execution_mode or "react")
    root = resolve_data_root(cfg.data_root)
    skill_dir = root / "tenants" / cfg.tenant_id / "skills" / skill_name

    if skill_dir.exists():
        _emit_stderr(f"Error: Skill '{skill_name}' already exists.")
        logger.debug("Existing skill directory: %s", skill_dir)
        return 1

    skill_dir.mkdir(parents=True)
    template = f"""---
name: {skill_name}
version: "1.0"
description: "Describe what this skill does"
execution_mode: {mode}
keywords:
  - example
---

# System Prompt

Instructions for the LLM when this skill is active.
"""
    (skill_dir / "SKILL.md").write_text(template, encoding="utf-8")

    _emit_stdout(f"Created skill '{skill_name}'.")
    _emit_stdout(f" Edit: {skill_dir / 'SKILL.md'}")
    _emit_stdout(f" Mode: {mode}")
    _emit_stdout("")
    _emit_stdout(" Don't forget to register in _index.yaml:")
    _emit_stdout(f" {skill_name}:")
    logger.debug("Created skill at %s", skill_dir)
    return 0


def cmd_info(_args: argparse.Namespace) -> int:
    """Show installation info."""
    cfg = _resolve_cli_config()
    data_root = resolve_data_root(cfg.data_root)

    _emit_stdout(f"IAF AgentOS v{__version__}")
    _emit_stdout(f" Model: {cfg.model}")
    _emit_stdout(f" Tenant: {cfg.tenant_id}")
    _emit_stdout(f" Data root: {data_root}")
    _emit_stdout("")

    optional = []
    for module_name, label in (
        ("langchain_core", "langchain-core"),
        ("yaml", "pyyaml"),
        ("redis", "redis"),
    ):
        try:
            __import__(module_name)
            optional.append(f"  {label}: installed")
        except ImportError:
            optional.append(f"  {label}: not installed")

    if optional:
        _emit_stdout("Optional dependencies:")
        for line in optional:
            _emit_stdout(line)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentos", description="IAF AgentOS CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    init_cmd = sub.add_parser("init", help="Scaffold enterprise_root structure")
    init_cmd.add_argument("--data-root", default=None)
    init_cmd.add_argument("--tenant", default=None)
    init_cmd.set_defaults(func=cmd_init)

    skill_cmd = sub.add_parser("skill", help="Skill management")
    skill_sub = skill_cmd.add_subparsers(dest="skill_command", required=True)

    list_cmd = skill_sub.add_parser("list", help="List registered skills")
    list_cmd.add_argument("--data-root", default=None)
    list_cmd.add_argument("--tenant", default=None)
    list_cmd.set_defaults(func=cmd_skill_list)

    create_cmd = skill_sub.add_parser("create", help="Create a new skill")
    create_cmd.add_argument("name")
    create_cmd.add_argument("--data-root", default=None)
    create_cmd.add_argument("--tenant", default=None)
    create_cmd.add_argument(
        "--execution-mode",
        choices=["react", "workflow", "parallel", "supervisor"],
        default="react",
    )
    create_cmd.set_defaults(func=cmd_skill_create)

    info_cmd = sub.add_parser("info", help="Show installation info")
    info_cmd.set_defaults(func=cmd_info)

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        _emit_stderr("Interrupted.")
        return 130
    except ValueError:
        logger.debug("CLI validation failed", exc_info=True)
        _emit_stderr("Error: invalid configuration.")
        return 1
    except Exception:
        logger.debug("CLI operation failed", exc_info=True)
        _emit_stderr("Error: operation failed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

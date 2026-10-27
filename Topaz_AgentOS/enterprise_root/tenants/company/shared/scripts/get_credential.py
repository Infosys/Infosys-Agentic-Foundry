#!/usr/bin/env python3
"""
Credential helper — called by skill STEP 0 to get a decrypted credential value.

Usage:
    python3 /shared/scripts/get_credential.py <credential_name> <field>

Examples:
    python3 /shared/scripts/get_credential.py ccd_k8s_api token
    python3 /shared/scripts/get_credential.py checkmk_api PWD
    python3 /shared/scripts/get_credential.py checkmk_api username

Prints the plaintext value to stdout. Exit 1 on failure.
"""

import os
import sys
from pathlib import Path

if len(sys.argv) < 3:
    print(f"Usage: {sys.argv[0]} <credential_name> <field>", file=sys.stderr)
    sys.exit(1)

cred_name = sys.argv[1]
field     = sys.argv[2]

_here = Path(__file__).resolve()
_project_root = None
for parent in _here.parents:
    if (parent / "agent_os" / "config.env").exists():
        _project_root = parent
        break

if not _project_root:
    print("ERROR: Could not find project root (agent_os/config.env)", file=sys.stderr)
    sys.exit(1)

# Explicit utf-8: config.env has non-ASCII headers that break the cp1252 default.
_env_path = _project_root / "agent_os" / "config.env"
for line in _env_path.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"'))

sys.path.insert(0, str(_project_root / "IAF-Agent-Skills"))
sys.path.insert(0, str(_project_root))  # needed so `import agent_os` resolves as package

from agent_os.credential_store import CredentialStore

config_dir = _project_root / "enterprise_root" / "tenants" / "company" / "shared" / "config"
store = CredentialStore.create(config_dir=config_dir)

# Consumer identity for scope-based access control, injected by the kernel sandbox.
consumer = os.environ.get("IAF_CURRENT_SKILL") or None

cred = store.get(cred_name, consumer=consumer, purpose="skill credential fetch")
if not cred:
    print(
        f"ERROR: Credential '{cred_name}' not found or not in scope for "
        f"'{consumer or 'unknown'}'",
        file=sys.stderr,
    )
    sys.exit(1)

value = cred.value.get(field)
if not value:
    print(f"ERROR: Field '{field}' not found in credential '{cred_name}'", file=sys.stderr)
    sys.exit(1)

print(value, end="")

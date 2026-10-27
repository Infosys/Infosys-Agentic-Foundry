"""Tests for the vision_readonly PreToolUse hook (on_block: deny).

Runs the hook script as a subprocess with the env vars hook_runner provides,
and asserts exit 0 (allow) / exit 1 + blocked JSON (deny).

Run:
    cd IAF_AgentOS_Harness_rlm
    PYTHONPATH="$PWD:$PWD/IAF-Agent-Skills" \
      <venv>/bin/python3 \
      -m pytest IAF-Agent-Skills/tests/test_vision_readonly_hook.py -v
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = str(_REPO_ROOT / "enterprise_root" / "tenants" / "company" / "shared" / "hooks" / "vision_readonly.py")


def run_hook(**env) -> subprocess.CompletedProcess:
    full = dict(os.environ)
    full.update({k: str(v) for k, v in env.items()})
    return subprocess.run([sys.executable, HOOK], capture_output=True, text=True, env=full)



def test_blocks_write_tool_in_classify_node():
    r = run_hook(IAF_SKILL_NAME="objdemo_classify", IAF_TOOL_NAME="create_restock_task",
                 IAF_TOOL_INPUT="{}")
    assert r.returncode == 1
    assert json.loads(r.stdout)["blocked"] is True


def test_blocks_write_sql_in_verify_node():
    r = run_hook(IAF_SKILL_NAME="objdemo_verify", IAF_TOOL_NAME="run_sql_query",
                 IAF_TOOL_INPUT='{"query": "UPDATE ap SET x=1"}')
    assert r.returncode == 1
    assert "vision_readonly" in json.loads(r.stdout)["reason"]


def test_blocks_when_forced_readonly_env():
    r = run_hook(IAF_VISION_READONLY="1", IAF_SKILL_NAME="anything",
                 IAF_TOOL_NAME="delete_record", IAF_TOOL_INPUT="{}")
    assert r.returncode == 1



def test_allows_jev_see_in_classify_node():
    r = run_hook(IAF_SKILL_NAME="objdemo_classify", IAF_TOOL_NAME="jev_see",
                 IAF_TOOL_INPUT="{}")
    assert r.returncode == 0


def test_allows_select_sql_in_verify_node():
    r = run_hook(IAF_SKILL_NAME="objdemo_verify", IAF_TOOL_NAME="run_sql_query",
                 IAF_TOOL_INPUT='{"query": "SELECT * FROM ap"}')
    assert r.returncode == 0


def test_allows_write_in_act_node():
    # act node is NOT a read/verify node → out of scope → writes allowed.
    r = run_hook(IAF_SKILL_NAME="objdemo_act", IAF_TOOL_NAME="create_restock_task",
                 IAF_TOOL_INPUT="{}")
    assert r.returncode == 0


def test_noop_outside_vision_scope():
    r = run_hook(IAF_SKILL_NAME="fa_ap", IAF_TOOL_NAME="create_invoice",
                 IAF_TOOL_INPUT="{}")
    assert r.returncode == 0


def test_allows_request_human_approval_in_read_node():
    # escalation is allowed — it's how a read node hands off, not a write.
    r = run_hook(IAF_SKILL_NAME="objdemo_verify", IAF_TOOL_NAME="request_human_approval",
                 IAF_TOOL_INPUT="{}")
    assert r.returncode == 0


def test_noop_when_no_tool():
    r = run_hook(IAF_SKILL_NAME="objdemo_classify", IAF_TOOL_NAME="", IAF_TOOL_INPUT="{}")
    assert r.returncode == 0

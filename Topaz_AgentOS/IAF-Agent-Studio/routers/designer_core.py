"""Pure helpers for the Skill Designer — import-light (json/re/yaml only) so they can be unit-tested
offline without pulling in FastAPI / shared.state. Validators are imported lazily inside the function."""
from __future__ import annotations

import json
import re

import yaml

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,62}$")


def parse_envelope(text: str) -> dict:
    """Extract the strict-JSON envelope from model output (tolerate a ```json fence or surrounding prose)."""
    if not text:
        raise ValueError("empty designer response")
    m = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    raw = m.group(1) if m else text
    try:
        return json.loads(raw)
    except Exception:
        i, j = raw.find("{"), raw.rfind("}")
        if i >= 0 and j > i:
            return json.loads(raw[i:j + 1])
        raise


def validate_envelope(env: dict) -> list:
    """Validate a draft by artifact_type, reusing the real validators. Returns a list of error strings."""
    at = (env or {}).get("artifact_type")
    errs: list = []
    if at in ("skill", "graph_skill"):
        sk = env.get("skill") or {}
        if not NAME_RE.match(sk.get("name") or env.get("name") or ""):
            errs.append("skill name must be snake_case (^[a-z][a-z0-9_]{1,62}$)")
        mode = sk.get("execution_mode", "react")
        if mode in ("workflow", "parallel") and not sk.get("steps"):
            errs.append(f"{mode} requires steps")
        if mode in ("supervisor", "orchestrator") and not sk.get("worker_skills"):
            errs.append(f"{mode} requires worker_skills")
        if at == "graph_skill":
            gy = env.get("graph_yaml")
            if not gy:
                errs.append("graph_skill requires graph_yaml")
            else:
                try:
                    from iaf_agent_skills.process_graph import validate_graph, compile_to_plan
                    g = yaml.safe_load(gy)
                    validate_graph(g)
                    compile_to_plan(g)
                except Exception as e:
                    errs.append(f"graph invalid: {e}")
    elif at == "workstream":
        try:
            from iaf_agent_skills.workstream_store import validate_workstream
            errs.extend(validate_workstream(env.get("workstream") or {}))
        except Exception as e:
            errs.append(f"workstream validate error: {e}")
    elif at == "cron":
        cr = env.get("cron") or {}
        if not cr.get("skill_name"):
            errs.append("cron.skill_name is required")
        if not cr.get("cron"):
            errs.append("cron.cron (expression) is required")
        else:
            try:
                from croniter import croniter
                if not croniter.is_valid(cr["cron"]):
                    errs.append(f"invalid cron expression: {cr['cron']}")
            except ImportError:
                pass
    else:
        errs.append(f"unknown artifact_type: {at!r}")
    return errs

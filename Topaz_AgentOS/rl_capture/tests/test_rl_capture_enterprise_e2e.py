"""Enterprise E2E validation: can RL-capture datasets actually train a model?

This is a *trainer-perspective* harness, not a unit test. It seeds a fresh store
with realistic scenarios, runs every exporter through the canonical
``rl_capture.cli.run_export`` path (the same one the CLI and HTTP API use, so the
PII/quality gates are exercised), and then validates each produced dataset the
way a model trainer would:

  * SFT / tool_sft  -> renderable by an HF chat template (apply_chat_template),
                       real structured tool-call arguments, non-empty targets.
  * DPO / rejection -> distinct chosen vs rejected.
  * KTO             -> prompt/completion + binary desirable label.
  * RFT             -> shaped scalar reward in [-1, 1] + messages.
  * eval            -> input + expected reference.
  * PII / secrets   -> nothing sensitive survives into any exported row
                       (either scrubbed, or the export is hard-blocked).

Run it standalone (prints a PASS/FAIL report) or under pytest:

    cd IAF_AgentOS_Harness_rlm
    python3 rl_capture/tests/test_rl_capture_enterprise_e2e.py
    # or:  python3 -m pytest rl_capture/tests/test_rl_capture_enterprise_e2e.py -q
"""

from __future__ import annotations

import json
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from rl_capture.core.schema import (
    CandidateKind,
    CandidateOutput,
    CaptureMeta,
    Message,
    ModelCall,
    Observation,
    PairProvenance,
    PolicyRef,
    PreferenceSignal,
    RewardChannel,
    RewardEvent,
    Role,
    SamplingParams,
    StepKind,
    TargetRef,
    TargetType,
    ToolCall,
    ToolCallSpec,
    Trajectory,
    TrajectoryStep,
)
from rl_capture.cli import run_export, ResidualPIIError
from rl_capture.store.sqlite_store import RLStore



def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cap(tenant: str = "acme", agent: str = "support_agent") -> CaptureMeta:
    return CaptureMeta(tenant_id=tenant, agent_id=agent, capture_time=_now())


def _policy() -> PolicyRef:
    return PolicyRef(provider="local_vllm", model="qwen2.5-7b-instruct", model_version="2025-09")



def seed_single_turn_qa(store: RLStore, *, good: bool = True) -> str:
    """A clean single-turn QA — the bread-and-butter SFT / eval row."""
    tid = f"traj_qa_{uuid.uuid4().hex[:8]}"
    question = "What is our standard refund window for enterprise contracts?"
    answer = (
        "Enterprise contracts carry a 30-day refund window from invoice date, "
        "extendable to 45 days with a signed amendment."
    )
    mc = ModelCall(
        id=f"{tid}:model:final",
        policy=_policy(),
        input_messages=[
            Message(role=Role.SYSTEM, content="You are a helpful enterprise support agent."),
            Message(role=Role.USER, content=question),
        ],
        output_messages=[Message(role=Role.ASSISTANT, content=answer)],
        prompt_tokens=42,
        completion_tokens=33,
    )
    traj = Trajectory(
        id=tid,
        session_id="sess_qa",
        task=question,
        policy=_policy(),
        steps=[
            TrajectoryStep(id=f"{tid}:step:0", index=0, kind=StepKind.MODEL_CALL,
                           model_call_id=mc.id),
        ],
        model_calls=[mc],
        terminal_status="success" if good else "error",
        tenant="acme",
        capture=_cap(),
        metadata={"skill": "policy_qa"},
    )
    store.record_trajectory(traj)
    store.record_candidate_output(CandidateOutput(
        id=f"{tid}:cand:orig", trajectory_id=tid, kind=CandidateKind.ORIGINAL,
        messages=[Message(role=Role.ASSISTANT, content=answer)],
        target=TargetRef(tid, TargetType.TRAJECTORY),
        source="agentpro_final_response", created_at=_now(), capture=_cap(),
    ))
    # A judgement signal so RFT has a real reward.
    store.record_reward_event(RewardEvent(
        id=f"rev_{uuid.uuid4().hex}", channel=RewardChannel.THUMBS,
        target=TargetRef(tid, TargetType.TRAJECTORY),
        raw_label="up" if good else "down", confidence=1.0,
        judge_id="end_user", created_at=_now(), capture=_cap(),
    ))
    return tid


def seed_tool_calling_agent(store: RLStore) -> str:
    """Multi-step tool-using agent — the tool_sft (agent distillation) signal.

    Two model calls, each emitting a *structured* tool call with a real argument
    dict and the available-tools menu attached, exactly like the live fine-grained
    capture path (record_model_call_event) produces.
    """
    tid = f"traj_agent_{uuid.uuid4().hex[:8]}"
    task = "Refund invoice INV-4821 and email the customer a confirmation."
    tools_menu = [
        {"type": "function", "function": {
            "name": "lookup_invoice",
            "description": "Fetch invoice details by id.",
            "parameters": {"type": "object", "properties": {
                "invoice_id": {"type": "string"}}, "required": ["invoice_id"]}}},
        {"type": "function", "function": {
            "name": "issue_refund",
            "description": "Issue a refund for an invoice.",
            "parameters": {"type": "object", "properties": {
                "invoice_id": {"type": "string"},
                "amount": {"type": "number"}}, "required": ["invoice_id", "amount"]}}},
    ]
    # Base trajectory (coarse blob) — model calls recorded separately below,
    # mirroring the real runtime where fine-grained calls arrive incrementally.
    traj = Trajectory(
        id=tid, session_id="sess_agent", task=task, policy=_policy(),
        terminal_status="success", tenant="acme", capture=_cap(),
        metadata={"skill": "billing_ops"},
    )
    store.record_trajectory(traj)

    # Step 1: agent decides lookup_invoice.
    mc1 = ModelCall(
        id=f"{tid}:model:{uuid.uuid4().hex[:12]}", policy=_policy(),
        input_messages=[
            Message(role=Role.SYSTEM, content="You are a billing operations agent. Use tools."),
            Message(role=Role.USER, content=task),
        ],
        output_messages=[Message(
            role=Role.ASSISTANT, content="",
            tool_calls=[ToolCallSpec(call_id="call_1", name="lookup_invoice",
                                     arguments={"invoice_id": "INV-4821"})])],
        sampling=SamplingParams(temperature=0.2, top_p=0.95, max_tokens=256),
        metadata={"available_tools": tools_menu, "status": "ok"},
    )
    store.record_model_call(tid, mc1)

    # Step 2: after observing the invoice, agent decides issue_refund.
    mc2 = ModelCall(
        id=f"{tid}:model:{uuid.uuid4().hex[:12]}", policy=_policy(),
        input_messages=[
            Message(role=Role.SYSTEM, content="You are a billing operations agent. Use tools."),
            Message(role=Role.USER, content=task),
            Message(role=Role.ASSISTANT, content="",
                    tool_calls=[ToolCallSpec(call_id="call_1", name="lookup_invoice",
                                             arguments={"invoice_id": "INV-4821"})]),
            Message(role=Role.TOOL, content='{"invoice_id":"INV-4821","total":250.0,"status":"paid"}',
                    tool_call_id="call_1"),
        ],
        output_messages=[Message(
            role=Role.ASSISTANT, content="",
            tool_calls=[ToolCallSpec(call_id="call_2", name="issue_refund",
                                     arguments={"invoice_id": "INV-4821", "amount": 250.0})])],
        sampling=SamplingParams(temperature=0.2, top_p=0.95, max_tokens=256),
        metadata={"available_tools": tools_menu, "status": "ok"},
    )
    store.record_model_call(tid, mc2)

    # Record the actual tool executions + observations for completeness.
    store.record_tool_call(tid, ToolCall(
        id="call_1", name="lookup_invoice", arguments={"invoice_id": "INV-4821"},
        output={"invoice_id": "INV-4821", "total": 250.0, "status": "paid"},
        status="ok", duration_ms=120))
    store.record_tool_call(tid, ToolCall(
        id="call_2", name="issue_refund", arguments={"invoice_id": "INV-4821", "amount": 250.0},
        output={"refund_id": "RF-9001", "status": "refunded"}, status="ok", duration_ms=340))

    # Positive judgement so tool_sft min_reward filtering would keep it.
    store.record_reward_event(RewardEvent(
        id=f"rev_{uuid.uuid4().hex}", channel=RewardChannel.HUMAN_APPROVAL,
        target=TargetRef(tid, TargetType.TRAJECTORY), raw_label="approve",
        confidence=1.0, judge_id="ops_reviewer", created_at=_now(), capture=_cap()))
    return tid


def seed_preference_pair(store: RLStore) -> str:
    """Human-correction preference pair — feeds DPO and rejection_sft."""
    tid = f"traj_pref_{uuid.uuid4().hex[:8]}"
    question = "Draft a one-line SLA breach apology to the customer."
    weak = "Sorry for the issue."
    strong = ("We sincerely apologize for the SLA breach on your account; we've "
              "credited your next invoice and assigned a dedicated engineer.")
    traj = Trajectory(
        id=tid, session_id="sess_pref", task=question, policy=_policy(),
        model_calls=[ModelCall(
            id=f"{tid}:model:final", policy=_policy(),
            input_messages=[Message(role=Role.USER, content=question)],
            output_messages=[Message(role=Role.ASSISTANT, content=weak)])],
        terminal_status="success", tenant="acme", capture=_cap(),
        metadata={"skill": "comms"},
    )
    store.record_trajectory(traj)
    orig = CandidateOutput(
        id=f"{tid}:cand:orig", trajectory_id=tid, kind=CandidateKind.ORIGINAL,
        messages=[Message(role=Role.ASSISTANT, content=weak)],
        target=TargetRef(tid, TargetType.TRAJECTORY, "cand_orig"),
        created_at=_now(), capture=_cap())
    fixed = CandidateOutput(
        id=f"{tid}:cand:fix", trajectory_id=tid, kind=CandidateKind.HUMAN_CORRECTION,
        messages=[Message(role=Role.ASSISTANT, content=strong)],
        target=TargetRef(tid, TargetType.TRAJECTORY, "cand_fix"),
        created_at=_now(), capture=_cap())
    store.record_candidate_output(orig)
    store.record_candidate_output(fixed)
    # Resolve via TargetType.STEP + candidate id; TRAJECTORY would collapse both sides to the final output.
    pref_ref = TargetRef(tid, TargetType.STEP, fixed.id)
    disp_ref = TargetRef(tid, TargetType.STEP, orig.id)
    store.record_preference_signal(PreferenceSignal(
        id=f"pref_{uuid.uuid4().hex}",
        context_ref=TargetRef(tid, TargetType.TRAJECTORY),
        preferred_ref=pref_ref,
        dispreferred_ref=disp_ref,
        provenance=PairProvenance.HUMAN_EDIT,
        channel=RewardChannel.HUMAN_EDIT, judge_id="editor",
        margin=0.9, created_at=_now(), capture=_cap()))
    # Also a KTO-style desirable/undesirable pair via reward events on candidates.
    store.record_reward_event(RewardEvent(
        id=f"rev_{uuid.uuid4().hex}", channel=RewardChannel.HUMAN_EDIT,
        target=pref_ref, raw_label="accept", confidence=1.0,
        judge_id="editor", created_at=_now(), capture=_cap()))
    store.record_reward_event(RewardEvent(
        id=f"rev_{uuid.uuid4().hex}", channel=RewardChannel.HUMAN_EDIT,
        target=disp_ref, raw_label="reject", confidence=1.0,
        judge_id="editor", created_at=_now(), capture=_cap()))
    return tid


def seed_pii_leak(store: RLStore) -> str:
    """Adversarial: response contains email, phone, and a Luhn-valid card.

    The export must either scrub these or hard-block. Nothing sensitive may
    survive into the written dataset.
    """
    tid = f"traj_pii_{uuid.uuid4().hex[:8]}"
    question = "Confirm the customer's contact and card on file."
    # 4111111111111111 is the canonical Visa test number (passes Luhn).
    leaky = ("Customer jane.doe@example.com, phone (415) 555-2671, "
             "card 4111 1111 1111 1111 on file.")
    traj = Trajectory(
        id=tid, session_id="sess_pii", task=question, policy=_policy(),
        model_calls=[ModelCall(
            id=f"{tid}:model:final", policy=_policy(),
            input_messages=[Message(role=Role.USER, content=question)],
            output_messages=[Message(role=Role.ASSISTANT, content=leaky)])],
        terminal_status="success", tenant="acme", capture=_cap(),
        metadata={"skill": "account_lookup"},
    )
    store.record_trajectory(traj)
    store.record_candidate_output(CandidateOutput(
        id=f"{tid}:cand:orig", trajectory_id=tid, kind=CandidateKind.ORIGINAL,
        messages=[Message(role=Role.ASSISTANT, content=leaky)],
        target=TargetRef(tid, TargetType.TRAJECTORY), created_at=_now(), capture=_cap()))
    store.record_reward_event(RewardEvent(
        id=f"rev_{uuid.uuid4().hex}", channel=RewardChannel.THUMBS,
        target=TargetRef(tid, TargetType.TRAJECTORY), raw_label="up",
        confidence=1.0, judge_id="end_user", created_at=_now(), capture=_cap()))
    return tid


def seed_failed_empty(store: RLStore) -> str:
    """Edge: a failed trajectory with an empty answer — must not crash exporters."""
    tid = f"traj_fail_{uuid.uuid4().hex[:8]}"
    traj = Trajectory(
        id=tid, session_id="sess_fail", task="Do the impossible.", policy=_policy(),
        model_calls=[ModelCall(
            id=f"{tid}:model:final", policy=_policy(),
            input_messages=[Message(role=Role.USER, content="Do the impossible.")],
            output_messages=[Message(role=Role.ASSISTANT, content="")])],
        terminal_status="error", tenant="acme", capture=_cap(),
        metadata={"skill": "unknown"},
    )
    store.record_trajectory(traj)
    return tid


def seed_degenerate_pref(store: RLStore) -> str:
    """Adversarial: a mis-wired preference whose two sides resolve to the SAME
    text (both refs point at the trajectory). The DPO exporter must DROP it
    rather than emit a zero-signal chosen==rejected row.
    """
    tid = f"traj_degen_{uuid.uuid4().hex[:8]}"
    answer = "A single canonical answer."
    traj = Trajectory(
        id=tid, session_id="sess_degen", task="Q?", policy=_policy(),
        model_calls=[ModelCall(
            id=f"{tid}:model:final", policy=_policy(),
            input_messages=[Message(role=Role.USER, content="Q?")],
            output_messages=[Message(role=Role.ASSISTANT, content=answer)])],
        terminal_status="success", tenant="acme", capture=_cap(),
        metadata={"skill": "comms"},
    )
    store.record_trajectory(traj)
    both = TargetRef(tid, TargetType.TRAJECTORY)  # both sides resolve identically
    store.record_preference_signal(PreferenceSignal(
        id=f"pref_{uuid.uuid4().hex}",
        context_ref=TargetRef(tid, TargetType.TRAJECTORY),
        preferred_ref=both, dispreferred_ref=both,
        provenance=PairProvenance.HUMAN_EDIT, channel=RewardChannel.HUMAN_EDIT,
        judge_id="editor", margin=0.0, created_at=_now(), capture=_cap()))
    return tid



def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


PII_MARKERS = ["jane.doe@example.com", "555-2671", "4111 1111 1111 1111",
               "4111111111111111", "(415)"]


def _assert_no_pii(rows: list[dict], report: list) -> None:
    blob = json.dumps(rows, ensure_ascii=False)
    leaked = [m for m in PII_MARKERS if m in blob]
    report.append(("PII never leaks into any dataset row", not leaked,
                   f"leaked={leaked}" if leaked else "clean"))


def _try_chat_template(rows: list[dict], report: list, *, with_tools: bool) -> None:
    """Prove rows render with a real HF chat template — the trainer's first step."""
    try:
        from transformers import AutoTokenizer
    except Exception as exc:  # pragma: no cover
        report.append(("HF chat template render", None, f"transformers unavailable: {exc}"))
        return
    tok = None
    for name in ("mlx-community/Qwen2.5-7B-Instruct-4bit", "mlx-community/Qwen3-8B-4bit",
                 "Qwen/Qwen2.5-0.5B-Instruct", "HuggingFaceTB/SmolLM2-135M-Instruct"):
        try:
            tok = AutoTokenizer.from_pretrained(name, local_files_only=True)
            break
        except Exception:
            continue
    if tok is None:
        report.append(("HF chat template render", None, "no tokenizer cached offline; structural check only"))
        return
    ok = 0
    for row in rows:
        msgs = row.get("messages")
        if not msgs:
            continue
        try:
            if with_tools and row.get("tools"):
                tok.apply_chat_template(msgs, tools=row["tools"], tokenize=False, add_generation_prompt=False)
            else:
                tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
            ok += 1
        except Exception as exc:
            report.append(("HF chat template render", False, f"row failed: {exc}"))
            return
    report.append((f"HF chat template render ({'with tools' if with_tools else 'plain'})",
                   ok > 0, f"{ok} rows rendered"))


def _run_and_validate(store: RLStore, tmp: Path, report: list) -> None:
    p = tmp / "sft.jsonl"
    res = run_export(store, kind="sft", output_path=p, limit=1000)
    rows = _read_jsonl(p)
    good = [r for r in rows if r.get("messages") and
            any(m.get("role") == "assistant" and (m.get("content") or "").strip() for m in r["messages"]) and
            any(m.get("role") == "user" for m in r["messages"])]
    report.append(("SFT rows have user+non-empty-assistant messages", len(good) > 0,
                   f"{len(good)}/{len(rows)} usable rows"))
    # No SFT row may have an empty assistant target.
    empty_targets = [r for r in rows if not any(
        (m.get("content") or "").strip() or m.get("tool_calls")
        for m in r.get("messages", []) if m.get("role") == "assistant")]
    report.append(("SFT drops empty-assistant-target rows (fix #3)", not empty_targets,
                   f"{len(empty_targets)} empty rows leaked" if empty_targets else "none"))
    _assert_no_pii(rows, report)
    # CC redaction keeps the trailing space.
    blob = "\n".join(json.dumps(r) for r in rows)
    report.append(("CC redaction preserves trailing space (fix #4)",
                   "[REDACTED_CC]on" not in blob,
                   "artifact present" if "[REDACTED_CC]on" in blob else "clean spacing"))
    _try_chat_template(good, report, with_tools=False)

    p = tmp / "tool_sft.jsonl"
    res = run_export(store, kind="tool_sft", output_path=p, limit=1000)
    rows = _read_jsonl(p)
    structured = []
    for r in rows:
        asst = [m for m in r.get("messages", []) if m.get("role") == "assistant" and m.get("tool_calls")]
        has_tools_menu = bool(r.get("tools"))
        has_struct_args = any(
            isinstance(tc.get("function", {}).get("arguments"), dict) and tc["function"]["arguments"]
            for m in asst for tc in m["tool_calls"])
        if asst and has_tools_menu and has_struct_args:
            structured.append(r)
    report.append(("tool_sft rows carry structured tool-call args + tool menu",
                   len(structured) > 0, f"{len(structured)}/{len(rows)} agent-distillation rows"))
    _assert_no_pii(rows, report)
    _try_chat_template(structured, report, with_tools=True)

    p = tmp / "dpo.jsonl"
    res = run_export(store, kind="dpo", output_path=p, limit=1000)
    rows = _read_jsonl(p)
    distinct = [r for r in rows if _dpo_chosen(r) and _dpo_rejected(r) and _dpo_chosen(r) != _dpo_rejected(r)]
    report.append(("DPO rows have distinct chosen vs rejected", len(distinct) > 0,
                   f"{len(distinct)}/{len(rows)} preference rows"))
    # The degenerate mis-wired pair must be dropped.
    identical = [r for r in rows if _dpo_chosen(r) and _dpo_chosen(r) == _dpo_rejected(r)]
    report.append(("DPO drops degenerate chosen==rejected pairs (fix #1)", not identical,
                   f"{len(identical)} degenerate rows leaked" if identical else "none"))
    _assert_no_pii(rows, report)

    p = tmp / "kto.jsonl"
    res = run_export(store, kind="kto", output_path=p, limit=1000)
    rows = _read_jsonl(p)
    labeled = [r for r in rows if _kto_label(r) is not None]
    report.append(("KTO rows carry a binary desirable label", len(labeled) > 0,
                   f"{len(labeled)}/{len(rows)} labeled rows"))
    _assert_no_pii(rows, report)

    p = tmp / "rft.jsonl"
    res = run_export(store, kind="rft", output_path=p, limit=1000)
    rows = _read_jsonl(p)
    rewarded = [r for r in rows if _rft_reward(r) is not None and -1.0 <= _rft_reward(r) <= 1.0]
    report.append(("RFT rows carry a shaped scalar reward in [-1,1]", len(rewarded) > 0,
                   f"{len(rewarded)}/{len(rows)} rewarded rows; sample={[_rft_reward(r) for r in rewarded[:5]]}"))
    _assert_no_pii(rows, report)

    p = tmp / "eval.jsonl"
    res = run_export(store, kind="eval", output_path=p, limit=1000)
    rows = _read_jsonl(p)
    cased = [r for r in rows if _eval_input(r) and _eval_expected(r)]
    report.append(("eval cases have input + expected reference", len(cased) > 0,
                   f"{len(cased)}/{len(rows)} eval cases"))
    _assert_no_pii(rows, report)


def _dpo_chosen(r: dict):
    return r.get("chosen") or r.get("preferred") or (r.get("messages") and None)
def _dpo_rejected(r: dict):
    return r.get("rejected") or r.get("dispreferred")
def _kto_label(r: dict):
    for k in ("label", "desirable", "kto_tag"):
        if k in r:
            return r[k]
    return None
def _rft_reward(r: dict):
    v = r.get("reward")
    if v is None:
        v = (r.get("metadata") or {}).get("reward")
    return v
def _eval_input(r: dict):
    return r.get("input") or r.get("prompt") or r.get("question") or (r.get("messages") and True)
def _eval_expected(r: dict):
    return (r.get("expected") or r.get("reference") or r.get("ideal")
            or r.get("expected_output") or r.get("expected_behavior"))



def build_store(tmp: Path) -> RLStore:
    store = RLStore(db_path=tmp / "rl.db")
    seed_single_turn_qa(store, good=True)
    seed_single_turn_qa(store, good=False)     # a failed/negative-reward turn
    seed_tool_calling_agent(store)
    seed_preference_pair(store)
    seed_degenerate_pref(store)
    seed_pii_leak(store)
    seed_failed_empty(store)
    return store


def run() -> bool:
    report: list[tuple[str, object, str]] = []
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        store = build_store(tmp)
        health = store.dataset_health()
        print(f"\nSeeded store health: {health}\n")
        _run_and_validate(store, tmp, report)

    print("=" * 78)
    print("ENTERPRISE RL-CAPTURE DATASET VALIDATION REPORT")
    print("=" * 78)
    passed = failed = skipped = 0
    for name, ok, detail in report:
        if ok is None:
            tag, mark = "SKIP", "~"
            skipped += 1
        elif ok:
            tag, mark = "PASS", "+"
            passed += 1
        else:
            tag, mark = "FAIL", "x"
            failed += 1
        print(f"[{mark}] {tag:4}  {name:52}  {detail}")
    print("-" * 78)
    print(f"PASS={passed}  FAIL={failed}  SKIP={skipped}")
    print("=" * 78)
    return failed == 0


def test_enterprise_rl_capture_datasets():
    assert run(), "one or more enterprise dataset validations failed"


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)

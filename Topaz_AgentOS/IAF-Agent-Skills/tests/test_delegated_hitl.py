"""Regression tests for delegated-HITL approval propagation.

When a skill delegates to another skill (invoke_skill / orchestrator / supervisor) and the
child pauses for human approval, that pause must be mirrored onto the session agent the UI
reads — otherwise the approval buttons never appear and the held tool call is lost.

These use lightweight stand-ins (no LLM / kernel) so they run in CI. A full end-to-end run
with real SkillAgents + the real HITL gate + an actual resume-executes-the-write is exercised
by scratchpad/be_hitl_e2e.py (needs Azure creds), which is not a CI unit test.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_here))                     # IAF-Agent-Skills → iaf_agent_skills
sys.path.insert(0, os.path.dirname(os.path.dirname(_here)))    # repo root → agent_os, agentos_model

from iaf_agent_skills.tool_governance import mirror_child_pause  # noqa: E402
from iaf_agent_skills.execution import SupervisorEngine, OrchestratorEngine  # noqa: E402
from iaf_agent_skills.tool_factory import create_invoke_skill_tool  # noqa: E402

SKILLS = Path(__file__).resolve().parents[1] / "iaf_agent_skills"


class _Parent:
    """Stand-in session agent: carries the three pause fields + the pending_action builder."""
    def __init__(self):
        self.pending_tool_call = None
        self.pending_action = None
        self.approval_pending = None

    def _build_stream_intercept_pending(self, skill_name=""):
        tc = self.pending_tool_call or {}
        self.pending_action = {
            "operation": tc.get("name", "tool"),
            "target": (tc.get("args") or {}).get("path", ""),
            "command": "__STREAM_INTERCEPT__",
            "skill": skill_name,
        }


class _PausedChild:
    """A child left paused after run() — a react write pause carries tool_call + approval_pending
    but not necessarily the legacy pending_action (the mirror must build that)."""
    def __init__(self, with_pending_action=False):
        self.pending_tool_call = {"name": "write_file", "args": {"path": "x.txt", "content": "y"}, "id": "c1"}
        self.pending_action = {"operation": "write", "reason": "write op"} if with_pending_action else None
        self.approval_pending = {"approval_id": "a1", "reason": "write op"}

    def run(self, *a, **k):
        return "CHILD_RESULT_SHOULD_NOT_SURFACE"


def test_mirror_copies_pause_and_builds_pending_action():
    parent, child = _Parent(), _PausedChild()
    notice = mirror_child_pause(parent, child, skill_name="writer", task="t")
    assert isinstance(notice, str) and "approval" in notice.lower()
    assert parent.pending_tool_call is child.pending_tool_call   # resumable
    assert parent.approval_pending is child.approval_pending      # durable / Command Center
    assert parent.pending_action is not None                      # inline card + dashboard surface


def test_mirror_prefers_childs_own_pending_action():
    parent, child = _Parent(), _PausedChild(with_pending_action=True)
    mirror_child_pause(parent, child, skill_name="writer")
    assert parent.pending_action is child.pending_action


def test_mirror_first_pause_wins():
    parent = _Parent()
    parent.pending_tool_call = {"name": "existing", "args": {}, "id": "keep"}
    parent.pending_action = {"operation": "existing"}
    assert mirror_child_pause(parent, _PausedChild(), skill_name="writer") is None
    assert parent.pending_tool_call["id"] == "keep"   # not clobbered


def test_mirror_noop_when_child_has_no_pause():
    parent = _Parent()
    child = _PausedChild()
    child.pending_tool_call = child.pending_action = child.approval_pending = None
    assert mirror_child_pause(parent, child) is None
    assert parent.pending_tool_call is None and parent.pending_action is None


def test_supervisor_retains_paused_worker():
    class _Worker:
        def __init__(self):
            self.approval_pending = None
        def run(self, task, skill_name=None):
            self.approval_pending = {"approval_id": "w1", "reason": "danger"}
            self.pending_tool_call = {"name": "shell", "args": {"command": "rm -rf x"}, "id": "w1"}
            self.pending_action = {"operation": "shell"}
            return "ran"
    w = _Worker()
    eng = SupervisorEngine(lambda name: w)
    eng.run("do it", [{"name": "writer", "task": "delete"}])
    assert eng.approval_pending is not None
    assert getattr(eng, "paused_child_agent", None) is w   # retained so the parent can mirror it


def test_orchestrator_captures_child_pause_and_halts():
    # The manager loop must HALT when a delegated child pauses — not keep calling _decide and
    # synthesise an answer built on an unapproved action.
    class _Resp:
        def __init__(self, c): self.content = c
    class _Mgr:
        def __init__(self): self.calls = 0
        def invoke(self, _msgs):
            self.calls += 1
            return _Resp('{"action": "call_skill", "skill_name": "writer", "task": "write x"}')
    mgr = _Mgr()
    eng = OrchestratorEngine(manager_llm=mgr, agent_factory=lambda _n: _PausedChild(),
                             available_skills=[{"name": "writer", "description": "writes"}], max_steps=5)
    out = eng.run("create a file")
    assert eng.approval_pending is not None                 # pause captured
    assert eng.paused_child_agent is not None               # child retained for mirror/resume
    assert len(eng.step_log) == 1                           # halted after ONE step
    assert mgr.calls == 1                                   # did NOT loop the manager past the pause
    assert "approval" in out.lower() and "completed" not in out.lower()


def test_invoke_skill_mirrors_child_pause_and_halts():
    parent = _Parent()

    class _Router:
        def match(self, task):
            return "writer"

    tool = create_invoke_skill_tool(router=_Router(), agent_factory_fn=lambda _n: _PausedChild(),
                                    current_depth=0, parent_agent=parent)
    out = tool.invoke({"task": "write a file", "context": "", "target_skill": "writer"})
    assert "approval" in out.lower()                 # halt notice, not the child's result
    assert "SHOULD_NOT_SURFACE" not in out
    assert parent.pending_tool_call is not None and parent.pending_action is not None


def test_invoke_skill_without_parent_is_the_old_bug():
    # Control: no parent_agent => nothing mirrors and the child result leaks (pre-fix behaviour).
    tool = create_invoke_skill_tool(router=None, agent_factory_fn=lambda _n: _PausedChild(),
                                    current_depth=0, parent_agent=None)
    out = tool.invoke({"task": "write a file", "context": "", "target_skill": "writer"})
    assert "SHOULD_NOT_SURFACE" in out


def test_wiring_present_in_source():
    # The session agent must pass itself as parent_agent, and the loop must halt on a mirrored pause.
    agent_src = (SKILLS / "agent.py").read_text(encoding="utf-8")
    assert "parent_agent=self" in agent_src
    assert 'return "__PENDING__"' in agent_src
    assert "mirror_child_pause(self," in agent_src   # orchestrator + supervisor wrappers


# ---------------------------------------- Copilot review round 5

class _Dec:
    """A minimal governance decision: anything not pending/blocked executes."""
    def __init__(self, status, tool_call_id):
        self.status = status
        self.tool_call_id = tool_call_id
        self.reason = ""


class _FakeLLM:
    """Scripted chat model for the native runtime: returns one AIMessage per turn."""
    def __init__(self, scripted):
        self._scripted = scripted
        self.invocations = 0
    def bind_tools(self, tools):
        return self
    def invoke(self, messages, config=None):
        msg = self._scripted[min(self.invocations, len(self._scripted) - 1)]
        self.invocations += 1
        return msg


class _FakeTool:
    def __init__(self, name, cb):
        self.name = name
        self._cb = cb
    def invoke(self, args, config=None):
        return self._cb(args)


def _native_runtime_with_invoke_skill(scripted, on_invoke):
    from iaf_agent_skills.react_runtime.native import NativeReactRuntime
    tool = _FakeTool("invoke_skill", on_invoke)
    return NativeReactRuntime(
        llm=_FakeLLM(scripted),
        tools=[tool],
        system_prompt="sys",
        max_iterations=5,
    )


def test_native_runtime_halts_on_delegated_pause():
    # #1: in the native loop a delegated child pause arrives as a tool RESULT (not a govern
    # decision). The loop must halt there — otherwise it calls the model again and runs past
    # the unapproved action.
    from langchain_core.messages import AIMessage, HumanMessage
    turn1 = AIMessage(content="", tool_calls=[{"id": "t1", "name": "invoke_skill", "args": {"task": "x"}}])
    turn2 = AIMessage(content="FINAL — SHOULD NOT BE REACHED")
    state = {"paused": False}

    def on_invoke(_args):
        state["paused"] = True   # the mirror armed a pause on the session agent
        return "⏸️ Delegated skill needs human approval. The action has NOT run yet."

    rt = _native_runtime_with_invoke_skill([turn1, turn2], on_invoke)
    out = rt.run(
        messages=[HumanMessage(content="do it")],
        config=None,
        govern_batch=lambda calls: [_Dec("allowed", c["id"]) for c in calls],
        check_delegated_pause=lambda: state["paused"],
    )
    assert out == "__PENDING__"
    assert rt.llm.invocations == 1          # did NOT call the model a second time
    assert rt.pending_resume is None        # delegated pause resumes via the agent's held-call path


def test_native_runtime_without_check_runs_past_pause_is_the_old_bug():
    # Control: with no check_delegated_pause the native loop keeps going (the pre-fix bug).
    from langchain_core.messages import AIMessage, HumanMessage
    turn1 = AIMessage(content="", tool_calls=[{"id": "t1", "name": "invoke_skill", "args": {"task": "x"}}])
    turn2 = AIMessage(content="kept going")
    rt = _native_runtime_with_invoke_skill([turn1, turn2], lambda _a: "⏸️ paused, not run yet")
    out = rt.run(
        messages=[HumanMessage(content="do it")],
        config=None,
        govern_batch=lambda calls: [_Dec("allowed", c["id"]) for c in calls],
    )
    assert isinstance(out, dict)            # reached a final answer
    assert rt.llm.invocations == 2          # looped the model past the pause


def test_tool_provider_contract_accepts_parent_agent():
    # #2: the shared ToolProvider contract + builtin + sample adapter all accept parent_agent,
    # so a conforming provider is not broken by the delegated-HITL wiring.
    import inspect
    from iaf_agent_skills.providers_default.builtin_tool_provider import BuiltinToolProvider
    from agentos_contracts.providers import ToolProvider
    from partner_adapters.sample_tool_provider import SampleToolProvider
    for cls in (BuiltinToolProvider, ToolProvider, SampleToolProvider):
        params = inspect.signature(cls.create_invoke_skill_tool).parameters
        assert "parent_agent" in params, f"{cls.__name__} must accept parent_agent"


def test_agent_has_provider_compatibility_path():
    # #2: agent.py passes parent_agent only when the provider's signature accepts it (so an
    # external provider still on the 3-arg contract doesn't raise TypeError).
    src = (SKILLS / "agent.py").read_text(encoding="utf-8")
    assert "_accepts_parent" in src
    assert "VAR_KEYWORD" in src   # signature-gated, not a blind try/except on TypeError


def test_mirror_stamps_child_skill_on_held_call():
    # #3: the mirror records the CHILD's skill on the held call so the resume scopes it to the
    # delegated skill (credentials / kernel current-skill / MCP attestation), not the parent's.
    class _ChildWithSkill(_PausedChild):
        current_skill = "writer"
    parent = _Parent()
    mirror_child_pause(parent, _ChildWithSkill(), skill_name="writer")
    assert (parent.pending_tool_call or {}).get("skill") == "writer"
    assert (parent.pending_action or {}).get("skill") == "writer"


def test_resume_scopes_to_held_call_skill_in_source():
    # #3: _restore_kernel_skill prefers the held call's skill over the session current_skill,
    # and the else-branch rebuilds tools when the bound skill differs from the held one.
    src = (SKILLS / "agent.py").read_text(encoding="utf-8")
    fn = src[src.index("def _restore_kernel_skill"): src.index("def execute_approved_action")]
    i_held = fn.index('pending_tool_call", None) or {}).get("skill")')
    i_cur = fn.index('getattr(self, "current_skill", None)')
    assert i_held < i_cur, "held-call skill must be preferred over current_skill"
    assert "_react_tools_skill" in src
    assert "_bound_skill != _scope_skill" in src


# ---------------------------------------- Copilot review round 6

def test_native_runtime_stops_batch_on_first_delegated_pause():
    # #2: when one model turn emits TWO invoke_skill calls and the first child pauses, the
    # second must NOT run — else mirror_child_pause's first-pause-wins discards its held call.
    from langchain_core.messages import AIMessage, HumanMessage
    turn1 = AIMessage(content="", tool_calls=[
        {"id": "t1", "name": "invoke_skill", "args": {"task": "a"}},
        {"id": "t2", "name": "invoke_skill", "args": {"task": "b"}},
    ])
    state = {"calls": [], "paused": False}

    def on_invoke(args):
        state["calls"].append(args.get("task"))
        state["paused"] = True   # the first delegated call pauses
        return "⏸️ paused, not run yet"

    rt = _native_runtime_with_invoke_skill([turn1, AIMessage(content="END")], on_invoke)
    out = rt.run(
        messages=[HumanMessage(content="do")],
        config=None,
        govern_batch=lambda calls: [_Dec("allowed", c["id"]) for c in calls],
        check_delegated_pause=lambda: state["paused"],
    )
    assert out == "__PENDING__"
    assert state["calls"] == ["a"]     # only the FIRST invoke_skill ran; the second was skipped
    assert rt.llm.invocations == 1


def test_native_resume_surfaces_new_pause_before_model_loop():
    # #3: an approved held invoke_skill that creates a NEW delegated pause must surface it from
    # resume_and_continue WITHOUT re-entering the model loop (which could clear it).
    from langchain_core.messages import AIMessage
    rt = _native_runtime_with_invoke_skill([AIMessage(content="MODEL RAN — WRONG")], lambda a: "ran")
    rt.pending_resume = {"messages": [], "collected": [], "tool_calls": [
        {"id": "h1", "name": "invoke_skill", "args": {"task": "x"}},
    ]}
    state = {"paused": False}

    def execute_held(_tc):
        state["paused"] = True   # approving the held call created a fresh delegated pause
        return "held ran"

    out = rt.resume_and_continue(
        config=None,
        govern_batch=lambda calls: [_Dec("allowed", c["id"]) for c in calls],
        execute_held=execute_held,
        check_delegated_pause=lambda: state["paused"],
    )
    assert out == "__PENDING__"
    assert rt.llm.invocations == 0     # the model loop was NOT re-entered


def test_resume_aborts_when_delegated_rebuild_fails():
    # #1: a failed rebuild for the delegated skill must ABORT the approval, not fall through to
    # the parent's stale tool map (where a same-named tool would run under the wrong scope).
    src = (SKILLS / "agent.py").read_text(encoding="utf-8")
    i_fail = src.index("aborting approval")
    i_return = src.index("could not load the tools for delegated skill", i_fail)
    assert i_fail < i_return


def test_restore_kernel_skill_invalidates_cached_agent():
    # #5: restoring a different skill must invalidate the cached LangGraph agent so the next
    # request rebuilds, instead of reusing the parent's graph for the restored skill.
    src = (SKILLS / "agent.py").read_text(encoding="utf-8")
    fn = src[src.index("def _restore_kernel_skill"): src.index("def execute_approved_action")]
    assert "if skill != _prev_skill:" in fn
    assert "self.agent = None" in fn

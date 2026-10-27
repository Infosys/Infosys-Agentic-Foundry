"""Recursive Language Model engine (Phase 0-1 read-only + Phase 3 v1 governed execution).

The model receives only METADATA about `context` (a big string variable) and programs over it in a
restricted REPL: it slices/greps `context`, calls a fresh sub-LLM (`llm_query`/`llm_query_batched`),
may recurse into a sub-RLM (`rlm_query`), may call injected GOVERNED tools by name, and answers with
FINAL(...).

Safety model:
- The executor is restricted (SAFE_BUILTINS: no import/open/eval/getattr). The ONLY way model code
  can reach a side effect is via a callable injected in `tools` — and the caller MUST inject only
  wrappers that route through the host's governance (govern_tool_call). The engine never calls a
  tool itself and never bypasses governance.
- Hybrid routing: `root_model_call` (capable) drives the reasoning loop; `leaf_model_call` (cheap)
  serves `llm_query`. Both are injected by the caller (in AgentOS, policy-wrapped so audit/RL apply).
- Bounded: leaf-call, tool-call, iteration, depth, and concurrency budgets + an optional wall-clock
  deadline and a cooperative cancel check (kill switch).

Transport/host-agnostic: no HTTP/UI imports.
"""
from __future__ import annotations

import ast
import builtins
import concurrent.futures
import contextlib
import io
import json
import re
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

# Restricted builtins — no __import__/open/eval/exec/getattr/etc. `re`/`json` are provided in ns.
_SAFE_NAMES = [
    "abs", "all", "any", "bool", "bytes", "dict", "divmod", "enumerate", "filter", "float",
    "format", "frozenset", "int", "isinstance", "issubclass", "len", "list", "map", "max",
    "min", "print", "range", "repr", "reversed", "round", "set", "slice", "sorted", "str",
    "sum", "tuple", "zip",
]
SAFE_BUILTINS = {n: getattr(builtins, n) for n in _SAFE_NAMES}

ROOT_SYSTEM = """You are a Recursive Language Model (RLM). Answer the QUERY using a CONTEXT that is
too large to read directly. The CONTEXT is a Python string variable `context` inside a restricted
REPL you control. You interact ONLY by writing Python code.

Environment:
- context : the full input as a string ({n} chars). Do NOT try to read it all at once.
- llm_query(prompt: str) -> str : ask a fresh sub-LLM about a CHUNK of `context`. Put a lot into
  each call; minimize the number of calls.
- llm_query_batched(prompts: list[str]) -> list[str] : run MANY sub-LLM calls CONCURRENTLY and get
  answers in order. PREFER this over a Python for-loop of llm_query when the chunk queries are
  independent — it is much faster.
{rlm_line}{tools_line}- print(...) : show yourself output (you only see a TRUNCATED preview each turn).
- the `re` and `json` modules are preloaded. `import`, file access, and OS access are DISABLED.

Rules:
1. Each turn write exactly ONE code block fenced as ```repl ... ```.
2. Slice/scan `context`, call llm_query on chunks, accumulate results in variables.
3. When certain, call FINAL(answer) INSIDE the code block (a string or a variable). Do not print
   the answer as prose. FINAL takes ONE argument.
4. The moment your code has the answer, call FINAL(...) on the next turn — do not re-verify more
   than once.

QUERY: {query}

Begin. Write your first ```repl block."""

RLM_QUERY_LINE = ("- rlm_query(sub_context: str, query: str) -> str : for a COMPLEX sub-task, run a\n"
                  "  sub-RLM over sub_context (its own chunk/aggregate pass). Use when a chunk is itself\n"
                  "  too big for one llm_query.\n")


class RLMCancelled(Exception):
    """Raised (and caught at the loop) when the run is cancelled or exceeds its wall-clock deadline."""


def extract_code(text: str) -> str:
    m = re.search(r"```(?:repl|python)?\s*\n(.*?)```", text, re.DOTALL)
    return m.group(1) if m else ""


# Escape-hatch / IO names that must never appear in RLM code. Most are already absent from
# SAFE_BUILTINS; rejecting them at parse time gives a clear message and blocks any reference.
_DISALLOWED_NAMES = frozenset({
    "eval", "exec", "compile", "__import__", "open", "getattr", "setattr", "delattr",
    "globals", "locals", "vars", "input", "breakpoint", "memoryview", "__builtins__",
})


def ast_guard(code: str) -> str | None:
    """Static pre-execution bouncer for the in-process RLM executor.

    Parses the code (without running it) and returns a reason string if it contains a disallowed
    construct — an `import`, a dunder attribute access (e.g. `.__class__`, `.__subclasses__`, the
    building blocks of restricted-exec escapes), or an escape-hatch/IO name — else None. Syntax
    errors are left for exec_capture to surface as a normal [EXCEPTION]. This hardens the
    language-level sandbox (it is not a substitute for OS-level isolation; see v2 plan).
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None  # let exec_capture report the SyntaxError the usual way
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return "import is disabled in the RLM sandbox"
        if isinstance(node, ast.Attribute):
            attr = node.attr or ""
            if len(attr) > 4 and attr.startswith("__") and attr.endswith("__"):
                return f"dunder attribute access '{attr}' is not allowed"
        if isinstance(node, ast.Name) and node.id in _DISALLOWED_NAMES:
            return f"use of '{node.id}' is not allowed"
    return None


def exec_capture(code: str, ns: dict) -> str:
    # Pre-execution AST guard: refuse escape-hatch/IO constructs before running anything.
    _violation = ast_guard(code)
    if _violation:
        return f"[blocked: {_violation}. Rewrite using the provided tools and safe operations only.]"
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            exec(code, ns)  # ns["__builtins__"] == SAFE_BUILTINS (set by caller)
    except RLMCancelled:
        raise  # never swallow a cancellation — it must stop the whole run
    except Exception as e:
        buf.write("\n[EXCEPTION]\n" + "".join(traceback.format_exception_only(type(e), e)))
    return buf.getvalue()


@dataclass
class RunState:
    """Shared across all depths/threads of one top-level run."""
    max_leaf_calls: int = 30
    max_tool_calls: int = 20
    leaf_calls: int = 0
    tool_calls: int = 0
    lock: "threading.Lock" = field(default_factory=threading.Lock)      # guards budget counters
    seq_lock: "threading.Lock" = field(default_factory=threading.Lock)  # guards the node-id counter
    run_id: str = ""
    deadline: float | None = None                     # time.monotonic() ceiling, or None
    cancel_check: Callable[[], bool] | None = None     # external kill switch
    _seq: int = 0

    def new_node_id(self) -> int:
        with self.seq_lock:
            self._seq += 1
            return self._seq

    def check_alive(self) -> None:
        if self.cancel_check is not None:
            try:
                if self.cancel_check():
                    raise RLMCancelled("cancelled")
            except RLMCancelled:
                raise
            except Exception:
                pass  # a broken cancel_check must not crash the run
        if self.deadline is not None and time.monotonic() > self.deadline:
            raise RLMCancelled("wall-clock deadline exceeded")


def _clip(s: Any, n: int = 4000) -> str:
    s = str(s)
    return s if len(s) <= n else s[:n] + f"… (+{len(s) - n} chars)"


def run_rlm(root_model_call: Callable[[str], str], context: str, query: str, *,
            leaf_model_call: Callable[[str], str] | None = None,
            tools: dict | None = None, tools_prompt: str = "",
            max_iters: int = 6, max_depth: int = 2, root_tokens: int = 2000,
            max_leaf_calls: int = 30, max_tool_calls: int = 20, max_concurrent: int = 4,
            deadline_s: float | None = None, cancel_check: Callable[[], bool] | None = None,
            run_id: str = "", emit: Callable[[dict], None] | None = None,
            run: RunState | None = None, depth: int = 0, parent_node: int = 0) -> tuple[str, dict | None]:
    """Run one RLM node.

    `root_model_call` drives the reasoning loop; `leaf_model_call` (defaults to root) serves
    `llm_query`. `tools` is an optional {name: callable} of ALREADY-GOVERNED wrappers merged into the
    REPL namespace. Returns (answer, metrics); metrics is populated only at depth 0.
    """
    emit_raw = emit or (lambda e: None)
    leaf_call = leaf_model_call or root_model_call
    top = run is None
    if top:
        run = RunState(max_leaf_calls=max_leaf_calls, max_tool_calls=max_tool_calls, run_id=run_id,
                       cancel_check=cancel_check,
                       deadline=(time.monotonic() + deadline_s) if deadline_s else None)

    my_node = run.new_node_id()

    def emit(ev: dict) -> None:  # stamp lineage on every event
        ev.setdefault("run_id", run.run_id)
        ev.setdefault("node_id", my_node)
        ev.setdefault("parent", parent_node)
        emit_raw(ev)

    def _one_call(prompt: Any) -> str:
        with run.lock:
            if run.leaf_calls >= run.max_leaf_calls:
                raise RuntimeError(f"leaf call budget ({run.max_leaf_calls}) exceeded")
            run.leaf_calls += 1
            n = run.leaf_calls
        run.check_alive()
        resp = leaf_call(str(prompt))
        emit({"type": "llm_query", "depth": depth, "n": n,
              "in_chars": len(str(prompt)), "prompt": _clip(prompt), "response": _clip(resp)})
        return resp

    def llm_query(prompt: Any) -> str:
        return _one_call(prompt)

    def llm_query_batched(prompts: Any) -> list:
        """Run many sub-LLM calls CONCURRENTLY (order-preserving). Bounded by max_concurrent."""
        items = list(prompts)
        results: list = [None] * len(items)
        if not items:
            return results
        workers = max(1, min(int(max_concurrent), len(items)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            fut_to_i = {ex.submit(_one_call, p): i for i, p in enumerate(items)}
            for fut in concurrent.futures.as_completed(fut_to_i):
                i = fut_to_i[fut]
                try:
                    results[i] = fut.result()
                except RLMCancelled:
                    raise
                except Exception as e:
                    results[i] = f"[llm_query error: {e}]"
        return results

    def rlm_query(sub_context: Any, q: Any) -> str:
        if depth >= max_depth:  # floor → degrade to a leaf call
            return llm_query(f"{q}\n\nCONTEXT:\n{str(sub_context)[:8000]}")
        emit({"type": "rlm_start", "depth": depth, "sub_chars": len(str(sub_context)), "query": str(q)})
        ans, _ = run_rlm(root_model_call, str(sub_context), str(q), leaf_model_call=leaf_call,
                         tools=tools, tools_prompt=tools_prompt, max_iters=max_iters,
                         max_depth=max_depth, root_tokens=root_tokens, max_concurrent=max_concurrent,
                         emit=emit_raw, run=run, depth=depth + 1, parent_node=my_node)
        emit({"type": "rlm_end", "depth": depth, "answer": _clip(ans)})
        return ans

    def _wrap_tool(name: str, fn: Callable) -> Callable:
        """Wrap an injected (already-governed) tool so calls are budgeted, cancel-checked, emitted."""
        def wrapped(*args, **kwargs):
            with run.lock:
                if run.tool_calls >= run.max_tool_calls:
                    raise RuntimeError(f"tool call budget ({run.max_tool_calls}) exceeded")
                run.tool_calls += 1
                tn = run.tool_calls
            run.check_alive()
            try:
                arg_preview = _clip(json.dumps({"args": args, "kwargs": kwargs}, default=str), 400)
            except Exception:
                arg_preview = _clip((args, kwargs), 400)
            emit({"type": "tool_call", "depth": depth, "name": name, "n": tn, "args": arg_preview})
            result = fn(*args, **kwargs)
            emit({"type": "tool_result", "depth": depth, "name": name, "result": _clip(result)})
            return result
        return wrapped

    state = {"final": None}
    ns: dict = {
        "context": context, "re": re, "json": json,
        "llm_query": llm_query, "llm_query_batched": llm_query_batched, "rlm_query": rlm_query,
        "FINAL": lambda x: state.__setitem__("final", str(x)),
        "FINAL_VAR": lambda name: state.__setitem__("final", str(ns.get(name, f"<var '{name}' not found>"))),
        "__builtins__": SAFE_BUILTINS,
    }
    for _tname, _tfn in (tools or {}).items():   # inject ONLY governed wrappers
        ns[_tname] = _wrap_tool(_tname, _tfn)

    rlm_line = RLM_QUERY_LINE if depth < max_depth else ""
    system = ROOT_SYSTEM.format(n=len(context), query=query, rlm_line=rlm_line, tools_line=tools_prompt)
    meta = f"context length = {len(context)} chars. first 300 chars: {context[:300]!r}"
    messages = [{"role": "system", "content": system}, {"role": "user", "content": meta}]

    iters = 0
    for it in range(1, max_iters + 1):
        iters = it
        try:
            run.check_alive()  # cooperative cancel / deadline between turns
            prompt = "\n\n".join(m["content"] for m in messages)
            resp = root_model_call(prompt)
            messages.append({"role": "assistant", "content": resp})

            code = extract_code(resp)
            if code.strip():
                emit({"type": "code", "depth": depth, "iter": it, "code": code})
                out = exec_capture(code, ns)
                if state["final"] is not None:
                    return _finish(top, state["final"], iters, run)
                preview = out[:1500]
                emit({"type": "stdout", "depth": depth, "chars": len(out), "preview": preview})
                messages.append({"role": "user", "content": f"[stdout preview — {len(out)} chars]\n{preview}"})
                continue
        except RLMCancelled as c:
            return _finish(top, f"<RLM stopped: {c}>", iters, run)

        # No code block — lenient FINAL fallback.
        mv = re.search(r"FINAL_VAR\(\s*([A-Za-z_]\w*)\s*\)", resp)
        if mv:
            return _finish(top, str(ns.get(mv.group(1), f"<var '{mv.group(1)}' not found>")), iters, run)
        mf = re.search(r"FINAL\((.*)", resp, re.DOTALL)
        if mf and mf.group(1).strip():
            return _finish(top, mf.group(1).strip().rstrip(")").strip(), iters, run)
        messages.append({"role": "user", "content": "Write a ```repl code block and call FINAL(answer) when done."})

    return _finish(top, "<no FINAL produced within max_iters>", iters, run)


def _finish(top: bool, answer: str, iters: int, run: RunState) -> tuple[str, dict | None]:
    if not top:
        return answer, None
    return answer, {"answer": answer, "root_iters": iters,
                    "leaf_calls": run.leaf_calls, "tool_calls": run.tool_calls}

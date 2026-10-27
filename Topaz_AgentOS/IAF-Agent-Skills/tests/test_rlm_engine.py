"""Offline tests for the RLM engine + context store (Phase 0-1, analytical).

Loads the modules by file path so the suite stays independent of the full agent framework.
Run: python3 tests/test_rlm_engine.py
"""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest

_BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "iaf_agent_skills", "rlm")


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_BASE, filename))
    mod = importlib.util.module_from_spec(spec)
    # Register BEFORE exec so `from __future__ import annotations` + @dataclass can resolve
    # string annotations via sys.modules[cls.__module__] (required on Python 3.11+).
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


engine = _load("rlm_engine_under_test", "engine.py")
cstore = _load("rlm_cstore_under_test", "context_store.py")
shadow = _load("rlm_shadow_under_test", "shadow.py")


class MockLM:
    """Scripted model_call. Distinguishes root turns (prompt carries the ROOT_SYSTEM banner)
    from leaf sub-calls (a chunk question)."""

    def __init__(self, root_scripts, leaf_reply="LEAF_RESULT"):
        self.root_scripts = list(root_scripts)
        self.leaf_reply = leaf_reply
        self.root_calls = 0
        self.leaf_calls = 0

    def __call__(self, prompt, max_tokens=1500):
        if "Recursive Language Model" in prompt:  # a root/sub-RLM turn
            i = min(self.root_calls, len(self.root_scripts) - 1)
            self.root_calls += 1
            return self.root_scripts[i]
        self.leaf_calls += 1                       # a leaf llm_query
        return self.leaf_reply


class TestEngine(unittest.TestCase):

    def test_direct_final(self):
        lm = MockLM(['```repl\nFINAL("the answer")\n```'])
        ans, m = engine.run_rlm(lm, "small context", "q")
        self.assertEqual(ans, "the answer")
        self.assertEqual(m["leaf_calls"], 0)

    def test_leaf_subcall(self):
        lm = MockLM(['```repl\nr = llm_query("classify")\nFINAL(r)\n```'], leaf_reply="PERSONS=3")
        ans, m = engine.run_rlm(lm, "big context", "q", max_depth=1)
        self.assertEqual(ans, "PERSONS=3")
        self.assertEqual(m["leaf_calls"], 1)
        self.assertEqual(lm.leaf_calls, 1)

    def test_batched_concurrent(self):
        lm = MockLM(['```repl\nrs = llm_query_batched(["a", "b", "c"])\nFINAL(",".join(rs))\n```'],
                    leaf_reply="X")
        ans, m = engine.run_rlm(lm, "big context", "q", max_depth=1, max_concurrent=3)
        self.assertEqual(ans, "X,X,X")          # order preserved
        self.assertEqual(m["leaf_calls"], 3)    # budget counted correctly (thread-safe)

    def test_batched_respects_budget(self):
        lm = MockLM(['```repl\nrs = llm_query_batched(["a", "b", "c", "d"])\nFINAL(str(sum(1 for r in rs if not r.startswith("[llm_query error"))))\n```'],
                    leaf_reply="X")
        ans, m = engine.run_rlm(lm, "big", "q", max_depth=1, max_concurrent=4, max_leaf_calls=2)
        self.assertEqual(m["leaf_calls"], 2)    # only 2 allowed; extras error out, not overrun

    def test_recursion_depth2(self):
        lm = MockLM([
            '```repl\na = rlm_query(context[:50], "count")\nFINAL(a)\n```',  # depth 0
            '```repl\nFINAL("42")\n```',                                     # depth 1 sub-RLM
        ])
        events = []
        ans, m = engine.run_rlm(lm, "X" * 200, "q", max_depth=2, emit=events.append)
        self.assertEqual(ans, "42")
        self.assertTrue(any(e["type"] == "rlm_start" for e in events))
        self.assertTrue(any(e["type"] == "rlm_end" for e in events))

    def test_leaf_budget_enforced(self):
        lm = MockLM([
            '```repl\nllm_query("a")\nllm_query("b")\nFINAL("x")\n```',  # 2nd call exceeds budget
            '```repl\nFINAL("done")\n```',
        ])
        ans, m = engine.run_rlm(lm, "big", "q", max_depth=1, max_leaf_calls=1)
        self.assertEqual(m["leaf_calls"], 1)

    def test_root_never_sees_full_context(self):
        # Engine only ever puts a 300-char preview of context into the root prompt.
        seen = {}
        big = "N" * 100000

        def lm(prompt, max_tokens=1500):
            seen["prompt_len"] = len(prompt)
            return '```repl\nFINAL("ok")\n```'
        engine.run_rlm(lm, big, "q")
        self.assertLess(seen["prompt_len"], 5000)


class TestEngineV1(unittest.TestCase):
    """Phase 3 v1 additions: hybrid routing, injected governed tools, budgets, cancel, lineage."""

    def test_hybrid_root_leaf(self):
        def root_call(p):
            return '```repl\nr = llm_query("x")\nFINAL(r)\n```'
        def leaf_call(p):
            return "LEAF"
        ans, m = engine.run_rlm(root_call, "ctx", "q", leaf_model_call=leaf_call, max_depth=1)
        self.assertEqual(ans, "LEAF")            # leaf served by leaf_call, not root_call
        self.assertEqual(m["leaf_calls"], 1)

    def test_injected_tool_governed_and_budgeted(self):
        calls = []
        def my_tool(x):
            calls.append(x)
            return f"ran:{x}"
        root = MockLM(['```repl\nr = my_tool("a")\nFINAL(r)\n```'])
        events = []
        ans, m = engine.run_rlm(root, "ctx", "q", tools={"my_tool": my_tool},
                                tools_prompt="- my_tool(x)\n", run_id="R1", emit=events.append)
        self.assertEqual(ans, "ran:a")
        self.assertEqual(calls, ["a"])
        self.assertEqual(m["tool_calls"], 1)
        self.assertTrue(any(e["type"] == "tool_call" and e.get("name") == "my_tool" for e in events))
        self.assertTrue(any(e["type"] == "tool_result" for e in events))
        # lineage stamped on every event
        self.assertTrue(all("run_id" in e and "node_id" in e and "parent" in e for e in events))
        self.assertTrue(all(e["run_id"] == "R1" for e in events))

    def test_only_injected_names_reachable(self):
        # restricted ns: open() is not reachable → error captured, run recovers (no crash)
        root = MockLM(['```repl\nopen("/etc/passwd")\n```', '```repl\nFINAL("done")\n```'])
        ans, _ = engine.run_rlm(root, "ctx", "q")
        self.assertEqual(ans, "done")

    def test_tool_budget(self):
        def t():
            return "ok"
        root = MockLM(['```repl\nt()\nt()\nt()\nFINAL("x")\n```'])
        _, m = engine.run_rlm(root, "ctx", "q", tools={"t": t}, max_tool_calls=2)
        self.assertEqual(m["tool_calls"], 2)     # 3rd blocked by budget

    def test_cancel(self):
        flag = {"c": False}
        def root_call(p):
            flag["c"] = True
            return '```repl\nprint("hi")\n```'   # never FINAL → would loop
        ans, _ = engine.run_rlm(root_call, "ctx", "q", max_iters=5, cancel_check=lambda: flag["c"])
        self.assertIn("stopped", ans)

    def test_deadline(self):
        def root_call(p):
            return '```repl\nprint("x")\n```'    # never FINAL
        ans, _ = engine.run_rlm(root_call, "ctx", "q", max_iters=5, deadline_s=-1)
        self.assertIn("stopped", ans)


class TestExecutorSafety(unittest.TestCase):
    def _ns(self):
        import json as _j
        import re as _re
        return {"context": "a1 b2", "re": _re, "json": _j,
                "__builtins__": engine.SAFE_BUILTINS, "FINAL": lambda x: None}

    def test_import_blocked(self):
        # AST guard refuses imports pre-execution.
        self.assertIn("blocked", engine.exec_capture("import os", self._ns()))

    def test_open_eval_blocked(self):
        self.assertIn("blocked", engine.exec_capture("open('/etc/passwd')", self._ns()))
        self.assertIn("blocked", engine.exec_capture("eval('1+1')", self._ns()))

    def test_re_and_print_allowed(self):
        out = engine.exec_capture("print(re.findall(r'\\d+', context))", self._ns())
        self.assertIn("['1', '2']", out)

    def test_dunder_escape_blocked(self):
        # The classic restricted-exec escape must be refused before it runs.
        escape = "().__class__.__bases__[0].__subclasses__()"
        out = engine.exec_capture(escape, self._ns())
        self.assertIn("blocked", out)
        self.assertIn("dunder attribute access", out)

    def test_getattr_and_globals_blocked(self):
        self.assertIn("blocked", engine.exec_capture("getattr(re, 'compile')", self._ns()))
        self.assertIn("blocked", engine.exec_capture("globals()", self._ns()))

    def test_ast_guard_direct(self):
        # Positive/negative on the guard function itself.
        self.assertIsNone(engine.ast_guard("x = [i*2 for i in range(3)]\nprint(sum(x))"))
        self.assertIsNone(engine.ast_guard("m = re.search(r'\\d+', context); print(m.group(0))"))
        self.assertIsNotNone(engine.ast_guard("y = ().__class__"))
        self.assertIsNotNone(engine.ast_guard("from os import system"))

    def test_normal_analysis_code_still_runs(self):
        # Representative RLM analysis: parsing, loops, dict aggregation, string methods.
        code = (
            "rows = [r.strip() for r in context.split() if r.strip()]\n"
            "agg = {}\n"
            "for r in rows:\n"
            "    agg[r[0]] = agg.get(r[0], 0) + 1\n"
            "print(sorted(agg.items()))"
        )
        out = engine.exec_capture(code, self._ns())
        self.assertNotIn("blocked", out)
        self.assertNotIn("EXCEPTION", out)


class TestContextStore(unittest.TestCase):
    def test_offload_get(self):
        s = cstore.ContextStore()
        s.offload("sess-1", "hello world")
        self.assertEqual(s.get("sess-1"), "hello world")
        self.assertIsNone(s.get("nope"))

    def test_overwrite_and_evict(self):
        s = cstore.ContextStore(max_sessions=2)
        s.offload("a", "A"); s.offload("b", "B"); s.offload("c", "C")  # evicts "a"
        self.assertIsNone(s.get("a"))
        self.assertEqual(s.get("c"), "C")
        s.offload("b", "B2")
        self.assertEqual(s.get("b"), "B2")


class TestShadow(unittest.TestCase):
    def test_overlap(self):
        self.assertEqual(shadow.word_overlap("a b c", "a b c"), 1.0)
        self.assertEqual(shadow.word_overlap("a b", "c d"), 0.0)
        self.assertGreater(shadow.word_overlap("aurora budget cut", "the aurora budget was cut"), 0.4)

    def test_build_record(self):
        rec = shadow.build_record(
            query="q", normal_answer="aurora budget cut 18%", rlm_answer="the budget was cut 18%",
            rlm_metrics={"root_iters": 2, "leaf_calls": 3}, context_chars=500000,
            ts=1234.5, session_id="s1", rlm_elapsed_ms=1200)
        self.assertEqual(rec["session_id"], "s1")
        self.assertEqual(rec["context_chars"], 500000)
        self.assertEqual(rec["rlm_leaf_calls"], 3)
        self.assertGreater(rec["overlap"], 0.3)

    def test_append_jsonl(self):
        import json as _j
        import tempfile
        p = os.path.join(tempfile.mkdtemp(), "sub", "rlm_shadow.jsonl")
        shadow.append_jsonl(p, {"a": 1})
        shadow.append_jsonl(p, {"a": 2})
        with open(p) as fh:
            rows = [_j.loads(x) for x in fh]
        self.assertEqual([r["a"] for r in rows], [1, 2])


if __name__ == "__main__":
    unittest.main()

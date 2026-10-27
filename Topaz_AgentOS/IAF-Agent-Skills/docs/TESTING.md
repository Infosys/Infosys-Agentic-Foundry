# IAF-Agent-Skills Testing Guide

## Quick Start

```bash
cd IAF-Agent-Skills
python tests/test_execution_engine.py
```

Expected output: `ALL TESTS PASSED! ✅`

---

## Test Suite Overview

### Location
```
IAF-Agent-Skills/
├── tests/
│   └── test_execution_engine.py   # Main test suite
└── TESTING.md                      # This file
```

### What Gets Tested

| Test Group | File(s) Tested | Tests |
|------------|----------------|-------|
| ExecutionMode | `execution.py` | Enum values, parsing, case-insensitivity, fallback |
| Step Dataclasses | `execution.py` | Step creation, from_dict, depends_on, StepResult |
| WorkflowEngine | `execution.py` | Execution order, failures, unknown actions, timing, callbacks |
| SkillLoader | `loader.py` | execution_mode parsing, steps parsing, legacy defaults |
| Backward Compatibility | `loader.py` | All legacy skills load correctly |

---

## When to Run Tests

**ALWAYS run tests after modifying:**
- `iaf_agent_skills/execution.py`
- `iaf_agent_skills/loader.py`
- `iaf_agent_skills/agent.py`
- `IAF-Agent-Studio/server.py` (skills API)
- Any `SKILL.md` file

---

## Test Details

### 1. ExecutionMode Tests

Tests the `ExecutionMode` enum and `get_execution_mode()` function:

```python
# Valid modes
ExecutionMode.REACT      # "react" - LLM-driven (default)
ExecutionMode.WORKFLOW   # "workflow" - deterministic steps
ExecutionMode.PARALLEL   # "parallel" - concurrent execution
ExecutionMode.SUPERVISOR # "supervisor" - meta-agent delegation
```

**Edge cases tested:**
- Case insensitivity: `"REACT"`, `"Workflow"` → correct enum
- Invalid values: `"invalid"`, `""`, `None` → fallback to REACT

### 2. Step Dataclass Tests

```python
@dataclass
class Step:
    name: str                              # Required
    action: str                            # 'shell', 'python', etc.
    params: Dict[str, Any] = {}            # Action parameters
    depends_on: List[str] = []             # Step dependencies
```

**Tests:**
- Basic creation with all fields
- Default values (empty depends_on)
- `Step.from_dict()` class method
- `StepResult` success/failure cases

### 3. WorkflowEngine Tests

| Test | Description |
|------|-------------|
| Execution order | Steps run in sequence: s1 → s2 → s3 |
| Failure handling | Failed steps captured, workflow continues |
| Unknown action | Returns error with available actions |
| Empty steps | Returns empty dict `{}` |
| Timing capture | `duration_ms` recorded correctly |
| Multiple actions | shell, python, file all work |
| Output references | `{{step.output}}` resolved |
| format_summary | Markdown summary generated |
| Status callback | Callbacks invoked for each step |

### 4. SkillLoader Tests

**New fields parsed from SKILL.md:**
```yaml
---
name: my_skill
execution_mode: workflow   # NEW - defaults to 'react'
steps:                     # NEW - workflow steps
  - name: step1
    action: shell
    params:
      command: "echo hello"
---
```

**Tests:**
- `workflow_test` loads with `execution_mode: workflow` and 4 steps
- Legacy skills (dilo, ar_ops, etc.) default to `react`
- Step structure validation

### 5. Backward Compatibility Tests

Ensures ALL existing skills still work:
- `dilo`
- `ar_ops`
- `invoice`
- `invoice_dbs`
- `weather`
- `general`

Each must:
- Load without errors
- Have `name`, `body`, `tools`, `execution_mode` attributes
- Default to `execution_mode: react`

---

## Adding New Tests

### For New Execution Modes

Add to `TestExecutionMode.run()`:

```python
# Test new mode
try:
    assert get_execution_mode('new_mode') == ExecutionMode.NEW_MODE
    results.success("Parse 'new_mode'")
except Exception as e:
    results.failure("Parse 'new_mode'", str(e))
```

### For New Engine Features

Add to `TestWorkflowEngine.run()`:

```python
# Test new feature
try:
    engine = WorkflowEngine({'shell': mock_shell})
    # ... your test logic
    assert condition, "Error message"
    results.success("New feature description")
except Exception as e:
    results.failure("New feature", str(e))
```

### For New Skills

Add to `TestBackwardCompatibility.run()`:

```python
skills = ['dilo', 'ar_ops', ..., 'new_skill']
```

---

## Integration Testing

### Live Server Test

After unit tests pass, verify with running server:

```bash
# 1. Start server
pkill -f "server.py" 2>/dev/null
cd IAF-Agent-Studio
python -B server.py &

# 2. Test skills API
curl -s http://127.0.0.1:8080/api/skills | python -m json.tool

# 3. Test workflow execution (in UI)
# Type: "run workflow test"
# Expected: All 4 steps complete with ✅
```

### Expected Server Log for Workflow

```
🔍 Router checking query: 'run workflow test'
⚙️ Using WORKFLOW execution mode for skill: workflow_test
⚙️ Starting workflow with 4 steps
⚙️ Workflow step 1/4: create_dir (shell)
✅ Step 'create_dir' completed in 0ms
⚙️ Workflow step 2/4: step1_write (shell)
✅ Step 'step1_write' completed in 0ms
⚙️ Workflow step 3/4: step2_append (shell)
✅ Step 'step2_append' completed in 0ms
⚙️ Workflow step 4/4: step3_read (shell)
✅ Step 'step3_read' completed in 0ms
```

---

## Troubleshooting

### Import Errors

If you see `No module named 'agent_os'`:
- Tests use direct module loading to avoid this
- If persists, ensure you're running from `IAF-Agent-Skills/` directory

### Test Failures

1. **ExecutionMode parse failure**: Check `get_execution_mode()` in execution.py
2. **Step creation failure**: Check `Step` dataclass definition
3. **Workflow execution failure**: Check `WorkflowEngine.run()` method
4. **Loader failure**: Check `SkillLoader.load()` for new field parsing

### Debugging

Add print statements in test:
```python
try:
    result = some_function()
    print(f"DEBUG: result = {result}")  # Add this
    assert condition
    results.success("Test")
except Exception as e:
    import traceback
    traceback.print_exc()  # Add this
    results.failure("Test", str(e))
```

---

## CI/CD Integration

Add to your CI pipeline:

```yaml
# .github/workflows/test.yml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: pip install pyyaml
      - name: Run tests
        run: python tests/test_execution_engine.py
```

---

## Test Coverage Summary

| Component | Coverage |
|-----------|----------|
| ExecutionMode enum | ✅ Full |
| get_execution_mode() | ✅ Full (incl. edge cases) |
| Step dataclass | ✅ Full |
| StepResult dataclass | ✅ Full |
| WorkflowEngine.run() | ✅ Full |
| WorkflowEngine._execute_step() | ✅ Via run() |
| WorkflowEngine._resolve_params() | ✅ Via output reference test |
| WorkflowEngine.format_summary() | ✅ Full |
| SkillLoader.load() (new fields) | ✅ Full |
| ParallelEngine | ⏳ Stub only (not implemented) |
| SupervisorEngine | ⏳ Stub only (not implemented) |

---

## Version History

| Date | Changes |
|------|---------|
| 2026-01-21 | Initial test suite for execution engine |
| | Added 15 unit tests |
| | Added backward compatibility tests |

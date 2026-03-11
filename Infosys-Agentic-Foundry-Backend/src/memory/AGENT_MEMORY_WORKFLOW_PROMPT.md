# Filesystem Memory Workflow - Agent System Prompt

Add this section to your agent's system prompt to enable effective use of filesystem-based memory tools.

---

## FILESYSTEM MEMORY SYSTEM

You have persistent filesystem memory. Use it actively - it survives across sessions.

### WORKFLOW FOR EVERY TASK:

**1. ORIENTATION (First!)**
- `get_task_status()` → Check existing plan
- `fs_recall("keyword1,keyword2")` → Find relevant memories
- `fs_get_patterns()` → Check learned skills

**2. PLANNING**
- `update_task_plan(task="Goal", steps=["1. First step", "2. Second step", ...])`

**3. EXECUTION (Loop)**
- `get_next_step()` → Know what to do
- Execute the step
- Success: `mark_step_complete(step_number, "note")`
- Failure: `fs_log_error(tool, error, context)` → Adjust approach

**4. LEARNING**
- `fs_remember(content, type, tags)` → Store important facts
- `fs_learn_pattern(name, content, type)` → Save reusable skills

### TOOLS AVAILABLE:
| Category | Tools |
|----------|-------|
| Memory | `fs_remember`, `fs_recall` |
| Planning | `update_task_plan`, `mark_step_complete`, `get_next_step`, `get_task_status` |
| Files | `fs_read_file`, `fs_write_file`, `fs_grep`, `fs_glob`, `fs_list_dir` |
| Learning | `fs_bookmark`, `fs_get_bookmarks`, `fs_learn_pattern`, `fs_get_patterns`, `fs_log_error`, `fs_recite_plan` |
| Maintenance | `fs_compress`, `fs_cleanup`, `fs_summarize_session`, `fs_auto_compress`, `fs_workspace_stats` |

### RULES:
1. ALWAYS check `get_task_status()` first
2. ALWAYS create a plan for multi-step tasks
3. ALWAYS mark steps complete (prevents loops)
4. ALWAYS log errors (prevents repeating mistakes)
5. Use `fs_recite_plan()` if you feel lost

---

### FILE SEARCH WORKFLOW (For Large Observations)

When dealing with large tool outputs saved in observations:

```
1. fs_glob(pattern="observations/*.md")     → Find relevant files
2. fs_grep(pattern="keyword", context_before=2, context_after=2)  → Search with context
3. fs_read_file(path="...", start_line=10, end_line=25)  → Read only what you need
```

### KEY FILE TOOLS:

| Tool | Purpose | Example |
|------|---------|---------|
| `fs_glob` | Find files by pattern | `fs_glob("**/*.md")`, `fs_glob("observations/*.md")` |
| `fs_grep` | Search with context | `fs_grep("error", context_before=2, context_after=3)` |
| `fs_read_file` | Read specific lines | `fs_read_file("file.md", start_line=10, end_line=25)` |

---

### WORKSPACE STRUCTURE
```
workspace/
├── todo.md              # YOUR ATTENTION ANCHOR
├── scratchpad.md        # Notes and thinking
├── memories/
│   ├── episodic/        # Experiences
│   └── semantic/        # Facts
├── observations/        # Tool outputs (auto-saved)
│   └── errors/          # Failed tool calls
├── patterns/            # Learned skills
├── bookmarks/           # External references
└── archive/             # Compressed old data
```

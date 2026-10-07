# Agent OS & Skill Agent Framework

## 1. Skill Agent Creation via Markdown (SKILL.md)

Skill agents are defined entirely through **Markdown files** — no code required. Each skill is a `SKILL.md` file that describes the agent's persona, instructions, available tools, and behavior rules in natural language.

**How It Works**

1. Create or edit a `SKILL.md` file describing the skill's purpose, persona, tool list, and constraints
2. The framework reads and parses the markdown at inference time
3. The parsed content becomes the system prompt for the LLM during the ReAct execution loop
4. No redeployment or restart needed — changes to `SKILL.md` take effect on the next inference call

**Agent Directory Layout**

Each agent is organized under its department with a consistent folder structure:

```
agent_workspaces/{department}/agentos_agents/{agent_id}/
├── agent_config.json              # Agent metadata (name, model, department)
├── enterprise_context/
│   ├── Enterprise_Context.md      # Org-wide context injected into all agents
│   └── policies/*.md             # Compliance & policy documents
├── skills/
│   ├── _index.yaml               # Skill registry (routes queries to skills)
│   └── {skill_name}/
│       ├── SKILL.md              # Skill definition (persona + tools + rules)
│       ├── config.json           # Skill-level config (model overrides, params)
│       └── additional_files/     # Supporting files (CSVs, templates, etc.)
└── .audit/
    └── tool_audit_*.jsonl        # Audit trail of tool executions
```

---

## 2. ReAct Execution Loop

The framework uses a single, robust execution mode: **ReAct (Reason + Act)**. The LLM iteratively reasons about the user's query, selects a tool, observes the result, and repeats until it can provide a final answer.

**Loop Mechanics**

1. **Reason** — LLM analyzes the current state (user query + tool results so far)
2. **Act** — LLM selects a tool and provides arguments
3. **Observe** — Tool executes, result is appended to conversation
4. **Repeat** — Loop continues until LLM produces a final answer (no tool call)

**Key Behaviors**

- **Max iterations** guard prevents infinite loops
- **Human-in-the-loop** integration pauses execution mid-loop when approval is required
- **Token budget tracking** — each iteration's token usage is accumulated
- **Error resilience** — tool failures are reported back to the LLM as observations, allowing graceful recovery

---

## 3. Skill Routing (Multi-Skill Agents)

When an agent has **multiple skills**, the framework automatically routes the user's query to the most relevant skill using an LLM-powered router.

**How Routing Works**

1. A skill index (`_index.yaml`) lists all available skills with short descriptions
2. The router presents the skill list to the LLM along with the user's query
3. The LLM selects the best-matching skill
4. The selected skill's `SKILL.md` is loaded and used for the ReAct loop

**Fallback Behavior**

- If only one skill exists, routing is skipped — the single skill is used directly
- If the router cannot determine a match, it defaults to the first skill or asks the user for clarification

---

## 4. Human-in-the-Loop (HITL)

The framework supports **approval gates** where sensitive tool executions pause and wait for human approval before proceeding.

**How HITL Works**

1. A tool is marked as requiring approval (via hook configuration or skill config)
2. During the ReAct loop, when the LLM requests that tool, execution **pauses**
3. The pending tool call (name + arguments) is returned to the UI
4. The user reviews and **approves** or **rejects** the tool call
5. On approval, the loop resumes from where it paused; on rejection, the LLM is informed and re-plans

**Integration**

- Works with the **Hook System** (see §8) — PreToolUse hooks can trigger approval gates
- UI surfaces the pending approval with full tool name and arguments for transparency

---

## 5. Enterprise Context Injection

Every agent automatically receives **organization-wide context** that shapes its behavior, policies, and domain knowledge.

**Context Sources**

| Source | Purpose |
|--------|---------|
| Enterprise Context (`.md`) | Org-wide rules, domain knowledge, terminology |
| Policy Documents (`.md`) | Compliance policies, SOPs, security guidelines |

**How It Works**

1. At inference time, the framework reads all enterprise context and policy files
2. This content is prepended to the system prompt (before the skill-specific content)
3. The LLM sees enterprise context as authoritative background — it cannot be overridden by user queries
4. Enables consistent behavior across all agents in a department

**Use Cases**

- Enforce compliance rules across all agents
- Inject company-specific terminology and acronyms
- Provide org chart or escalation paths
- Set tone/formality standards

---

## 6. Multi-Skill Composition

A single agent can host **multiple skills**, each defined by its own `SKILL.md`. This allows building agents that cover broad domains without creating separate agents for each sub-task.

**Example**

```
Agent: "IT Operations Assistant"
├── Skill: network_troubleshooter     → Diagnoses connectivity, DNS, firewall issues
├── Skill: server_provisioning        → Provisions VMs, configures OS, sets up monitoring
├── Skill: incident_management        → Creates/updates tickets, escalates incidents
└── Skill: knowledge_base_search      → Searches internal docs and runbooks
```

**Benefits**

- **Single entry point** — users interact with one agent regardless of task type
- **Separation of concerns** — each skill has its own tools, rules, and persona
- **Independent updates** — modify one skill without affecting others
- **Automatic routing** — the framework picks the right skill based on the query

---

## 7. Token Usage & Cost Tracking

The framework tracks token consumption per inference call, providing visibility into LLM costs.

**Tracked Metrics**

- **Prompt tokens** — tokens sent to the LLM (system prompt + conversation + tool results)
- **Completion tokens** — tokens generated by the LLM (reasoning + tool calls + final answer)
- **Total tokens** — sum of prompt + completion
- **Per-iteration breakdown** — token usage for each ReAct loop iteration

**Benefits**

- Token counts are returned in the inference response payload
- Can be aggregated for billing, budgeting, and optimization
- Helps identify skills that are token-heavy and need optimization

---

## 8. Hook System (Pre-Tool, Post-Tool, Pre-Response)

The framework provides a powerful **hook system** that intercepts execution at key points, enabling custom logic without modifying core agent code.

**Hook Types**

**8.1 PreToolUse Hook**

**Fires:** Before a tool executes  
**Can:** Modify tool arguments, block tool execution, require human approval

**Use Cases:**

- Block dangerous commands (e.g., `rm -rf /`)
- Sanitize inputs (e.g., redact PII from queries)
- Enforce approval for production-impacting tools
- Rate-limit tool calls

**8.2 PostToolUse Hook**

**Fires:** After a tool executes, before the result reaches the LLM  
**Can:** Modify tool output, block result propagation, log/audit

**Use Cases:**

- Redact sensitive data from tool outputs before LLM sees it
- Enrich tool results with additional context
- Log all tool outputs for compliance
- Transform output format

**8.3 PreResponse Hook**

**Fires:** After the LLM produces its final answer, before sending to the user  
**Can:** Modify the response, block it, add disclaimers

**Use Cases:**

- Append compliance disclaimers
- Filter inappropriate content
- Add citations or source links
- Format response for specific channels (Teams, Slack, etc.)

**External Script Hooks**

In addition to built-in hooks, the framework supports **external hook scripts** that run before/after tool execution. This allows teams to plug in custom validation logic written in any language.

**Configuration**

Hooks are configured per-agent or globally. They can be enabled/disabled without restarting the server.

---

## Summary

| # | Feature | Description |
|---|---------|-------------|
| 1 | Skill Creation via SKILL.md | Define agents using natural language markdown — no code |
| 2 | ReAct Execution Loop | Iterative reason-act-observe loop for reliable task completion |
| 3 | Skill Routing | LLM-powered query routing across multiple skills |
| 4 | Human-in-the-Loop | Approval gates for sensitive tool executions |
| 5 | Enterprise Context | Org-wide policies and context injected into all agents |
| 6 | Multi-Skill Composition | Multiple skills per agent with automatic routing |
| 7 | Token Tracking | Per-call token usage metrics for cost visibility |
| 8 | Hook System | Pre-tool, post-tool, and pre-response interception points |

---

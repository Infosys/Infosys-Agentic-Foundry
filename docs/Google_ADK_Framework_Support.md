# Google ADK Framework Support

The framework now supports **Google Agent Development Kit (ADK)** as an inference backend alongside **LangGraph**. All six agent templates are available on both backends with feature parity. The backend choice does not affect the API surface — both expose the same endpoints and request/response contracts.

!!! info "Supported Templates"

    1. React Agent
    2. React-Critic Agent
    3. Planner-Executor Agent
    4. Planner-Executor-Critic Agent
    5. Meta (Supervisor) Agent
    5. Planner-Meta Agent

---

## Architecture

**1. LangGraph**

Workflows are built as explicit `state graphs` — each step is a named node, and transitions between steps are defined as conditional or unconditional edges. The entire graph is compiled into a single executable unit. State flows through a typed dictionary that is passed from node to node.

**2. Google ADK**

Workflows are built as `compositional agent trees` — instead of a flat graph, agents are nested inside higher-order agents that control sequencing and looping. The key building blocks are:

- `LLM Agent` — A single agent backed by an LLM with tools and instructions.
- `Sequential Agent` — Runs a list of sub-agents one after another.
- `Loop Agent` — Repeats its sub-agents until a break condition is met or a max iteration limit is reached.
- `Router Agent` — Selects and runs one sub-agent based on a runtime decision (used in planner-executor patterns).

There is no explicit graph definition. Workflow structure is expressed entirely through agent composition.

---

## Implementation Differences

| Aspect | LangGraph | Google ADK |
|--------|-----------|------------|
| `Workflow definition` | Nodes and edges in a state graph | Nested agent tree (sequential, loop, router) |
| `State` | Typed dictionary threaded through graph nodes | Session state dictionary; mutated via callbacks |
| `Feedback loops` | Conditional edges route back to earlier nodes | Loop agent repeats sub-agents; a callback inspects state and breaks the loop when done |
| `Routing / branching` | Conditional edges with router functions | Router agent picks a sub-agent at runtime |
| `Tool format` | LangChain tool wrappers | ADK native tools and function tools |
| `MCP tools` | Adapter layer over MCP servers | First-class MCP support (stdio and streamable HTTP transports) |
| `Multi-agent delegation` | Sub-graph invocations | Worker agents are wrapped as callable tools for a supervisor agent |
| `Message types` | LangChain message classes | Google GenAI Content / Part types |
| `Streaming` | Stream writer callbacks on graph nodes | Async event iterator from the ADK runner |
| `Session management` | LangGraph checkpointers | ADK session service with resumability support |

---

## Feature Support

All six templates support the following features on the Google ADK backend:

| Feature | Description |
|---------|-------------|
| `Online Evaluation` | Scores responses on fluency, relevancy, coherence, and groundedness (0–1 scale). Loops back with feedback if score < 0.7. |
| `Validation` | Validates responses against predefined criteria using tool-based or LLM-based validators. Criteria are matched to queries via semantic similarity. |
| `Plan Verification` | User approval step before plan execution (applicable to planner templates only). |
| `Response Formatting` | Formats the final response into structured UI components (canvas view). |
| `SSE Streaming` | Real-time event streaming to the client during agent execution. |
| `MCP Tools` | Native support for MCP servers via stdio and streamable HTTP transports. |
| `Episodic Memory` | Injects relevant past interactions as positive/negative examples to guide the agent. |
| `Tool Interrupt` | Pauses execution before tool calls for user review. |

---

## Quality Assessment Loop

**1. LangGraph Approach**

Validation and evaluation run as `separate sequential cycles` — the validator completes its full retry cycle first, and then the evaluator runs its own retry cycle independently.

**2. Google ADK Approach**

Validation and evaluation are combined into a `single unified quality loop`:

```text
┌──────────────────────────────────────────┐
│            Quality Loop (max 3)          │
│                                          │
│   Main Agent  →  Validator?  →  Evaluator?  │
│       ↑                              │   │
│       └──── improvement feedback ────┘   │
│                                          │
│   Exit when:                             │
│   • Both passed (score ≥ 0.7)            │
│   • Max iterations reached               │
└──────────────────────────────────────────┘
```

The loop composition adapts based on which flags are enabled:

| Flags Enabled | Agents in Loop |
|---------------|----------------|
| Neither | No loop — simple agent execution |
| Validator only | Main Agent → Validator |
| Evaluator only | Main Agent → Evaluator |
| Both | Main Agent → Validator → Evaluator |

**Key differences from LangGraph:**

- Validator and evaluator share a `single iteration counter` (max 3 total, not separate cycles).
- The loop exits only when `both` pass, or max iterations is reached.
- If either check fails, `combined feedback` from both is injected into the next iteration.

---

## Template Workflows

**1. React Agent**
:   User Query → React Agent (with tools) → Response

**2. React-Critic Agent**
:   User Query → *[Loop: Executor Agent → Critic Agent]* → Response

**3. Planner-Executor Agent**
:   User Query → Planner → *(Plan Verification?)* → *[Loop: Execute Steps]* → Response Generator

**4. Planner-Executor-Critic Agent**
:   User Query → Planner → *(Plan Verification?)* → *[Loop: Executor + Critic]* → Response Generator

**5. Meta (Supervisor) Agent**
:   User Query → Supervisor ←→ Worker Agents → Response

**6. Planner-Meta Agent**
:   User Query → Planner → *(Plan Verification?)* → Supervisor ←→ Workers → Response Generator

!!! Note
    When evaluation or validation flags are enabled, the main processing stage in each template is wrapped inside the unified quality loop described above.

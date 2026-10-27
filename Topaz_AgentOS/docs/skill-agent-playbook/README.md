# Building Skill-Based Agents — A Practical Playbook

*A vendor-neutral reference for authoring portable agents and for the platforms that run them.*

This guide is deliberately **not tied to any single framework**. It describes a
pattern — the *skill-based agent* — and the platform contract a *harness* must
honour to run such agents safely, portably, and observably. The vocabulary
(skill, capability, hook, hard gate, planner, harness) is generic; map it onto
whatever product you use.

---

## How to read this

| Part | For whom | Question it answers |
|---|---|---|
| **Part 1 — Concept & Architecture** | Everyone, incl. leads & decision-makers | *What is a skill-based agent, and why structure it this way?* |
| **Part 2 — Building a Skill** | Engineers & skill authors | *How do I actually build and package one?* |
| **Part 3 — Structuring Context** | Skill authors & domain experts | *How do I organise the knowledge a skill reasons over?* |
| **Part 4 — Harness Capabilities** | Platform / infrastructure teams | *What must our runtime provide to host these safely?* |
| **Part 5 — Checklists** | Both | *Are we doing it right? Is our harness ready?* |

Read Part 1 if you read nothing else — it is the shared mental model the rest
depends on.

---

# Part 1 — The Concept & Reference Architecture

## 1.1 The shift: from monolithic agent to skill-based agent

A first-generation agent tends to be a **monolith**: one large prompt, a fixed
tool list, and business logic, knowledge, security, and presentation all tangled
into the same code path. It works for one use case and one team. It does not
travel, it is hard to govern, and every new behaviour means editing the core.

A **skill-based agent** inverts this. The reasoning engine stays small and
general. Everything around it — *what it knows, what it can do, what it's
allowed to do, how it shows results* — is factored into discrete, declarative,
replaceable units called **skills**, running on a shared platform called a
**harness**.

The payoff:

- **Composability** — new behaviour = a new skill, not a rewrite.
- **Portability** — a well-packaged skill can run on more than one harness.
- **Governance** — security and audit live in the platform, uniformly, not
  sprinkled through prompts.
- **Testability** — each skill has a bounded contract you can test in isolation.

## 1.2 The reference architecture (the mental model)

Think in four layers. Data and control flow top to bottom; trust decreases as
you go up, so the lower layers are the ones that must never be bypassed.

```
        Entry points:  Chat · API · Schedule/Cron · Queue · Another agent
                                   │
                                   ▼
        ┌───────────────────────────────────────────────┐
        │   PLANNER / REASONING CORE  (the LLM loop)       │   ← decides WHAT to do
        └───────────────────────────────────────────────┘
                                   │
                                   ▼
        ┌───────────────────────────────────────────────┐
        │   CAPABILITY BOUNDARIES  (replaceable modules)   │   ← PERFORM the work
        │   tools · models · credentials · evidence ·      │
        │   memory · approvals · routing · scheduling      │
        └───────────────────────────────────────────────┘
                                   │
                                   ▼
        ┌───────────────────────────────────────────────┐
        │   LIFECYCLE HOOKS  (around each boundary)        │   ← OBSERVE / GATE / ENRICH
        │   before · after · error · blocked · resume      │
        └───────────────────────────────────────────────┘
                                   │
                                   ▼
        ┌───────────────────────────────────────────────┐
        │   HARD SECURITY GATES  (always enforced)         │   ← cannot be skipped
        │   sandbox · path safety · credential vault ·     │
        │   entitlement · mandatory approval               │
        └───────────────────────────────────────────────┘
```

**What lives where:**

- **Planner core** decides *what* to do next. It plans, calls capabilities, and
  reacts to results. It does not contain business rules or security checks.
- **Capabilities** *do* the work — execute a tool, call a model, resolve a
  credential, persist evidence, write memory, ask a human. Each is a module
  behind a stable interface, so it can be swapped (e.g. a different model
  provider or evidence store) without touching the agent.
- **Hooks** wrap capability lifecycle events. They *observe* (audit, trace),
  *gate* (allow/deny before an action), *enrich* (add context), or *route*
  (notify, escalate). They are how you add governance without editing the core.
- **Hard gates** are the non-negotiable safety controls. They run regardless of
  what the planner or a hook decides. Sandboxing, filesystem path safety,
  credential authorisation, entitlement checks, and mandatory human approval
  belong here.

## 1.3 The three golden rules

1. **Don't put business logic inside hooks.** Hooks observe, gate, enrich, and
   route. The *work* belongs in capabilities; the *decision of what work to do*
   belongs in the planner. Hooks that start "doing the task" become a shadow
   monolith.
2. **Don't put security inside the LLM.** A prompt that says "only approve
   invoices under €25k" is guidance, not a control. Real limits live in hard
   gates and gating hooks that the model cannot talk its way past.
3. **Defence in depth.** When a hook checks something a hard gate also checks
   (credentials, external access), keep both. Hooks add visibility and policy;
   gates are the floor.

## 1.4 Glossary (six terms used throughout)

- **Skill** — a self-contained unit of capability + knowledge + governance that
  the agent can route to for a class of tasks. Not just a prompt.
- **Harness** — the runtime/platform that loads skills, runs the planner loop,
  provides capabilities, fires hooks, and enforces hard gates.
- **Capability** — a replaceable module behind a stable interface (model
  provider, tool executor, credential resolver, evidence store, …).
- **Hook** — a handler that fires at a lifecycle event (before/after a tool, a
  step, a model call, an approval) and may observe or gate it.
- **Hard gate** — a security control the platform always enforces and that
  nothing upstream can disable.
- **Skill pack** — a portable folder bundling a skill's definition, knowledge,
  tools, hooks, viewers, and a manifest, so it can be installed on a compatible
  harness.

---

# Part 2 — Building a Skill

## 2.1 What a skill *is* (and isn't)

A skill is **a unit of capability, knowledge, and governance** — not merely a
system prompt. A good skill bundles:

- the **instructions/persona** that tell the planner how to behave for this task,
- the **knowledge** it reasons over (policies, playbooks, schemas),
- the **tools** it may use,
- the **governance** it carries (approval thresholds, what it may touch),
- optionally, **presentation** (how results are shown) and **tests**.

If you find yourself writing one enormous prompt that does everything, that is a
sign to split it into several skills with a routing or orchestrator skill on top.

## 2.2 Anatomy of a skill package

A portable skill is a folder. Only a few items are mandatory; the rest are
opt-in.

```
my_skill/
├── manifest.(yaml|json)     ★ portability header — what the host reads to install
├── DEFINITION.(md|yaml)     ★ the agent definition: persona + instructions + metadata
├── README.md                ★ what it does, how to install, examples
│
├── contexts/                ◆ knowledge: policy.md, playbook.md, glossary.md, schema.md
├── tools/                   ◆ custom capabilities (small programs with a declared I/O contract)
│
├── hooks/                   ○ lifecycle handlers, scoped to THIS skill
├── viewers/                 ○ HTML/result cards for chat (inline) or standalone pages
├── fixtures/                ○ demo seed data so it runs out of the box
└── tests/                   ○ portable smoke tests (input → expected/forbidden output)
```

★ required · ◆ what a *typical* skill has · ○ add when the use case needs it

| Tier | Contains | Use when |
|---|---|---|
| **Minimal** | manifest + definition + (one of contexts/ or tools/) | Advisor / prompt-plus-knowledge skill |
| **Typical** | + contexts/ + tools/ + README | Most real skills |
| **Full / enterprise** | + hooks/ + viewers/ + fixtures/ + tests/ | Regulated, human-in-the-loop, or customer-facing skills |

## 2.3 The manifest — the portability contract

The manifest is the single most important file for "run anywhere." The
**definition** is read by the *agent runtime* (it shapes the prompt); the
**manifest** is read by the *host installer* (it decides whether the host can
run this skill at all). Keep them aligned.

A manifest should declare, at minimum:

- **Identity** — name, version (semver), description, authors, licence, tags.
- **Execution type** — `react` (reason-act loop), `workflow` (fixed steps),
  `parallel`, `supervisor`, or `orchestrator` (delegates to other skills).
- **Recommended model — by capability and tier, never by exact model ID.**
  e.g. `primary: { tier: frontier }`, `light: { tier: fast }`. This is what
  keeps a skill model-agnostic; the host maps tier → a concrete model it has.
- **Requirements** — the tools, storage, network, and hooks the host must
  provide. The host can then install, refuse, or degrade gracefully.
- **Inputs** — values the deployer sets at install (mark secrets as secrets).
- **Outputs** — the structured artifacts the skill produces (so other skills or
  systems can chain off them).
- **Callable sub-skills** — dependencies on other skills, with version ranges.

> **Principle:** a skill declares *what it needs*, never *how the host provides
> it*. That separation is the whole portability story.

## 2.4 Tools — custom capabilities

When a skill needs to do something the platform's built-in tools don't cover,
ship a small program in `tools/` with:

- a **declared specification** — a name, a human-readable description (the
  planner reads this to decide when to call it), and typed parameters;
- a **simple, sandbox-agnostic I/O contract** — e.g. read a JSON request,
  write a JSON result; raise/return an error the host can surface to the planner.

Rules for portable tools:

- **Assume nothing about the sandbox.** Treat all I/O as gated; never reach
  outside the skill's allotted space.
- **Never embed secrets.** Receive them as declared inputs the host injects.
- **Be deterministic and bounded** — cap runtime, output size, and side effects.

## 2.5 Hooks — governance scoped to the skill

A skill can carry its own lifecycle hooks (e.g. a "before tool" gate, an "after
tool" audit) that fire **only when this skill is active**. This is how a skill
brings its own compliance without polluting other skills.

Good practice:

- Scope hooks to the skill *and* to the specific event/tool they care about.
- Keep **gating hooks** (the ones that can block) fast and synchronous;
  keep **observing hooks** (audit, telemetry) able to run after the fact.
- A hook should fail *safe*: if a security-relevant hook errors, prefer to deny;
  if an observational hook errors, prefer to continue and log.

## 2.6 Viewers — presentation

If results benefit from richer display than text, ship a self-contained HTML
viewer: **inline** (a card rendered in the chat surface) or **standalone**
(opens as its own page). The skill **must still work headless** — a host that
can't render HTML should ignore the viewer, not fail.

## 2.7 The authoring workflow

1. **Decompose.** State the job in one sentence. If it needs "and," consider
   splitting into multiple skills + an orchestrator.
2. **Define.** Write the definition: persona, instructions, triggers, execution
   type, and the tools it may use.
3. **Add knowledge.** Put policies/playbooks/schemas in `contexts/`; reference
   them from the definition.
4. **Wire tools.** Add only the tools the skill genuinely needs (least
   privilege). Declare them in both the definition and the manifest.
5. **Add governance.** Encode approval thresholds and what the skill may touch.
   Add scoped hooks for audit/gating if the domain requires it.
6. **Add human-in-the-loop** where a decision is consequential or irreversible.
7. **Test.** Write smoke tests (happy path + a "must refuse" path). Ship
   fixtures so it runs in a demo without external systems.
8. **Package.** Add the manifest and README; validate against the spec.

## 2.8 Design principles

- **Single responsibility.** One skill, one job. Compose, don't bloat.
- **Declarative over imperative.** Prefer configuration (thresholds, tool lists,
  policies) over code where you can.
- **Least privilege.** Request the smallest tool/data/network footprint.
- **Model-agnostic.** Recommend by tier, not by a specific model.
- **Headless-first.** Viewers are enhancements, never requirements.
- **Fail closed on anything sensitive** (secrets, money, irreversible actions).
- **Idempotent and resumable** where possible — long or human-gated work should
  survive a restart.

## 2.9 Anti-patterns to avoid

- A mega-prompt that quietly does ten jobs.
- Security rules expressed only as prompt text.
- Hardcoded model IDs, hostnames, ports, or credentials.
- Tools that assume a specific filesystem or run with ambient privileges.
- Hooks that perform the task instead of governing it.
- "Knowledge" baked into the prompt that should be a versioned context file.

## 2.10 Worked example (generic): an "invoice triage" skill

- **Minimal:** a definition that explains triage rules + a `contexts/policy.md`
  with the approval matrix. No custom tools; it reasons over what it's told.
- **Typical:** add a `tools/fetch_invoice` tool (declared spec, JSON in/out) so
  it pulls live invoice data, and a `contexts/schema.md` describing the data.
- **Full:** add a scoped **post-tool audit hook** (records every data lookup), a
  **human-approval** step for payments above a threshold, an **inline viewer**
  that renders the triage decision as a card, `fixtures/` with sample invoices,
  and `tests/smoke.yaml` asserting it escalates a high-value invoice and refuses
  to auto-approve it.

The same skill, three tiers — start minimal, grow as the use case demands.

---

# Part 3 — Structuring Context: The Knowledge Hierarchy

A skill is only as good as the knowledge it reasons over. The naïve approach —
paste every policy and playbook into the prompt — blows the token budget, buries
the signal in noise, and gets slower and less accurate as the corpus grows. The
fix is to **structure knowledge as a hierarchy and inject only the slice that
matches the request.**

This part is primarily for **skill authors and domain experts**, but it directly
shapes what the harness's router/loader (Part 4) has to do.

## 3.1 Two artifacts

1. **A root index** — one top-level map, read first on every request. It lists
   the business **domains**, the **skills** that serve each, **routing cues**
   (the keywords/aliases users actually say), and **pointers** to the deeper
   files. It is a routing table, not a knowledge dump.
2. **A layered taxonomy** — the actual domain knowledge, organised into levels
   (L1–L5) of increasing specificity. The router scores a request against this
   tree and injects only the matching branch.
3. *(supporting)* **Per-skill references** — a short list, declared by each
   skill, of reusable files it always wants loaded (e.g. a specific playbook).
   One file can be referenced by many skills — **author once, reuse everywhere.**

## 3.2 The five levels

| Level | Generic meaning | What it holds |
|---|---|---|
| **L1 — Domain** | The broadest business area | Name, scope, the skills that serve it, pointers to deeper files |
| **L2 — Process group** | A major capability area within the domain | A heading that groups related processes |
| **L3 — Process** | **The unit that maps to exactly one skill** | The smallest *routable* unit; bound to a skill |
| **L4 — Sub-process** *(optional)* | A grouping of related activities | Used only when an L3 is large enough to need internal structure |
| **L5 — Activity** | An atomic task (verb + noun) | The **leaf** a request is matched against; carries a 1–2 line description |

The key idea: **the deeper you go, the more specific.** L1 says *"Finance"*; L5
says *"reconcile a duplicate vendor invoice."* Matching happens at the **leaf**,
and each leaf carries its **full path** (L1 → … → L5), so when it's embedded or
scored, *"restart the crashed service"* lands next to other infrastructure tasks
— not next to unrelated activities that merely share a word.

## 3.3 Two principles that make it work

- **Progressive disclosure.** Never inject the whole tree. Score the request,
  select the matching branch(es), load only those. Each turn stays cheap and
  focused no matter how large the total corpus grows.
- **Specificity ladder + full-path leaves.** Every level narrows scope; the leaf
  prepends its ancestry so matches are unambiguous. Descriptive leaves are what
  let *informal* language ("vendors aren't getting paid") match the right
  *formal* process ("accounts-payable payment run").

## 3.4 How the hierarchy drives routing

Two signals typically feed the router *before* the model makes its final call:

- an **identity signal** — *who/what* is involved (a specific customer, vendor,
  system)? — resolved from the root index's entity registry;
- a **process signal** — *what* is being asked? — resolved by scoring the
  request against the L5 leaves.

The router combines them to pick the skill and the context branch to inject. Two
consequences worth designing for:

- **Cross-domain requests** that score against leaves in *two* branches return
  *two* skills → the harness should fan out (orchestrate) and synthesise, rather
  than forcing one skill to handle both.
- **Graceful fallback** — if nothing scores above threshold, routing falls back
  to the model reasoning over the root index alone. The hierarchy *accelerates*
  and *sharpens* routing; it must never be a single point of failure.

## 3.5 What each level should contain (authoring guidance)

- **L1** — domain name, a one-line scope, the skills that serve it, and pointers
  to its taxonomy + reference files.
- **L2** — a grouping header; no logic.
- **L3** — bound to **exactly one skill**. That binding is what makes the level
  routable. If a process seems to need two skills, it is two L3 entries.
- **L5** — a verb-noun activity name **plus a 1–2 sentence description**, and
  optionally risk/severity/compliance tags and references to the
  exception/playbook files to load when this activity routes. *Terse leaves
  match poorly — write them as a human would describe the task.*

## 3.6 A minimal generic example

```
Domain: Widget Operations              (L1)
  Process group: Widget Lifecycle      (L2)
    Process: Widget Provisioning       (L3 → skill: widget_ops)
      Activities (L5):
        - Allocate widget pool         — reserve widgets from the shared pool for a team
        - Decommission expired widget  — remove end-of-life widgets and release quota
        - Rotate widget credentials    — refresh access keys for the widget integration
```

A request like *"how do I get widgets for my project?"* scores against
*"Allocate widget pool,"* resolves to `widget_ops`, and the harness injects only
the Widget-Provisioning branch — not the entire Widget Operations corpus.

## 3.7 Do / Don't

**Do**
- Map one process (L3) to one skill.
- Write descriptive L5 leaves so informal queries match.
- Reuse a context file across skills instead of copying it.
- Let domain experts own the markdown; keep it free of code.
- Version the hierarchy — it is curated knowledge; treat it like source.

**Don't**
- Dump the whole tree into the prompt.
- Bury durable knowledge inside a skill's instruction text (put it in context).
- Duplicate the same playbook across five skills (reference one file).
- Write leaves so terse that nothing matches them.

## 3.8 Context vs. memory — keep them distinct

The context hierarchy is **curated, authored knowledge** — relatively static,
versioned, owned by domain experts. It is *not* the same as **memory** (the
*learned*, accumulated state from past runs, covered as a harness capability in
Part 4). A healthy system keeps the two separate: edit the hierarchy when policy
changes; let memory grow from experience. Letting learned, possibly-stale facts
override authored policy is a common source of non-deterministic behaviour.

---

# Part 4 — What the Harness Must Provide

A skill-based agent is only as good as the platform under it. This is the
**capability contract** a harness should honour so that skills run safely and
travel well. For each capability: *what it is · why it matters · what "good"
looks like.*

## 4.1 Capability catalogue

**1. Tool execution**
*What:* a uniform way to run the planner's chosen tools.
*Why:* tools are how an agent affects the world; this is the highest-risk path.
*Good:* every tool call goes through one path that is logged, sandboxed, and
hookable — built-in tools and skill-supplied tools alike.

**2. Model provider (swappable, tiered)**
*What:* resolves a requested capability tier (frontier/fast/fallback) to a
concrete model.
*Why:* keeps skills model-agnostic and lets you change providers centrally.
*Good:* one resolution point; no skill names a specific model; per-tenant or
per-environment overrides are possible.

**3. Credential resolver + vault**
*What:* supplies secrets to tools without exposing them to the planner or logs.
*Why:* secrets must never enter prompts, traces, or previews.
*Good:* secrets are referenced by name, injected at the boundary, redacted
everywhere, and access is authorised and audited.

**4. Policy / entitlement engine**
*What:* decides whether *this* principal may take *this* action on *this*
resource.
*Why:* multi-tenant safety and least privilege.
*Good:* declared skill requirements are the *upper bound*; the host may further
restrict per tenant. Checks are enforced, not advisory.

**5. Evidence / audit collector**
*What:* records what the agent did — tools, inputs (redacted), decisions,
approvals — under a correlation/trace ID.
*Why:* audit, debugging, compliance, and trust.
*Good:* one persistence boundary used by every entry point (chat, schedule,
queue), with a stable record format and a trace ID that spans the whole run.

**6. Memory & learning**
*What:* durable recall across runs (history, learned facts, knowledge index).
*Why:* continuity and improvement over time.
*Good:* every write is observable and attributable; recall is consistent;
stale/contradictory memory can be pruned. *(Watch out: inconsistent memory will
make an agent behave non-deterministically — treat memory hygiene as a feature.)*

**7. Approval / human-in-the-loop (HITL)**
*What:* pause for a human decision, then resume with that decision in context.
*Why:* consequential or irreversible actions need a human gate.
*Good:* pause/resume survives restarts; the approver's decision (and any note)
flows back into the agent; the whole cycle is hookable and audited.

**8. Skill router / loader**
*What:* picks the right skill for a request and loads its definition, knowledge,
tools, and scoped hooks.
*Why:* it's the entry to everything a skill bundles.
*Good:* routing is explainable; loading a skill brings *all* of its package,
scoped correctly; unknown skills fail safe.

**9. Scheduler & queue runtime**
*What:* runs agents from time triggers (cron) and work queues, not just chat.
*Why:* most enterprise work is autonomous, not interactive.
*Good:* scheduled/queued runs go through the *same* capabilities, hooks, and
gates as chat — no second, less-governed runtime.

**10. Lifecycle hooks**
*What:* the event system that lets hooks observe/gate around capabilities.
*Why:* it's how governance is added without editing the core.
*Good:* a documented set of events, the ability to **scope a hook to a skill**
and/or a tool, clear gate-vs-observe semantics, and a fail policy. (See 4.2.)

**11. Hard security gates**
*What:* controls that always run: sandbox, path safety, credential
authorisation, entitlement, mandatory approval.
*Why:* the floor that nothing upstream can lower.
*Good:* enforced in the runtime itself; independent of (and in addition to)
hooks; a host that can't provide them must flag the agent as "untrusted mode."

**12. Observability / diagnostics**
*What:* read-only views into what's registered and what's happening — capability
inventory, tool-execution snapshots, drift/parity between declared and live.
*Why:* you can't trust or migrate what you can't inspect.
*Good:* bounded, redacted endpoints/views operators can query without changing
state.

**13. Packaging & portability**
*What:* install a skill from a portable package via its manifest; degrade
gracefully when an optional capability is missing.
*Why:* author once, run on more than one harness.
*Good:* the host reads the manifest, validates requirements, maps them to its
own primitives, and refuses clearly when a *required* capability is absent.

## 4.2 Lifecycle hooks — the events to support

A capable harness exposes (at least) these points. "Can block" means a hook may
veto the action before it happens.

| Event | Fires | Can block? |
|---|---|---|
| Before tool | before any tool runs | Yes |
| After tool | after a tool completes | No (post-mortem) |
| Before step | before an orchestrator/workflow step | Yes |
| After step | after a step | No |
| Before model call | before an LLM invocation | Yes |
| After model call | after an LLM invocation | No |
| On error | a tool/step threw or timed out | Compensation |
| Before / after approval resume | around resuming a human-gated run | Yes / No |
| Before / after schedule fire | around a scheduled run | Yes / No |
| On memory write / knowledge pending | background learning events | No |

Two properties make this genuinely useful:

- **Scoping** — a hook can be limited to a specific skill and/or a specific tool,
  so a skill can carry its own governance that fires only for itself.
- **Fail policy** — each gating hook declares whether a failure means *deny*
  (fail closed) or *proceed with warning* (fail open). Security-relevant hooks
  should fail closed.

## 4.3 Hard gates — the non-negotiables

A host must provide, and never let anything disable:

1. **Sandbox** for any shell/code execution — no direct host filesystem access.
2. **Path safety** — file writes cannot escape the agent's allotted space.
3. **Credential vault** — named secrets never appear in prompts, logs, or
   previews.
4. **Entitlement enforcement** — declared requirements are the ceiling; tenant
   policy may lower it.
5. **Mandatory audit** — every tool call, step, and approval recorded with a
   trace ID and the skill/version that caused it.

## 4.4 A capability maturity model

Most capabilities mature through three stages. You don't need stage 3 everywhere
on day one — but you should know where each capability sits.

1. **Observe** — the capability runs and is *logged*; hooks can watch it. (Get
   visibility first.)
2. **Gate** — hooks/policies can *block* it; hard gates enforce limits.
3. **Swap** — the capability sits behind a stable interface and can be *replaced*
   (different provider/store) without touching skills.

A pragmatic rollout: make everything *observable*, then *gate* the risky paths
(tools, credentials, approvals), then make the high-value capabilities *swappable*
(model provider and evidence store are usually the easiest wins).

---

# Part 5 — Checklists

## 5.1 Skill author checklist

- [ ] One clear responsibility; split if it needs an "and."
- [ ] Manifest declares identity, execution type, **model by tier**, required
      tools/storage/network/hooks, inputs (secrets marked), outputs.
- [ ] Definition and manifest agree (esp. execution type and tool list).
- [ ] Knowledge lives in `contexts/`, not hardcoded in the prompt.
- [ ] Tools follow least privilege; no embedded secrets; bounded I/O.
- [ ] Governance encoded (approval thresholds; what it may touch).
- [ ] HITL on consequential/irreversible actions.
- [ ] Scoped hooks for audit/gating where the domain needs it.
- [ ] Works headless (viewers optional).
- [ ] Smoke tests incl. a "must refuse" case; fixtures for offline demo.
- [ ] No hardcoded model IDs, hosts, ports, or paths.

## 5.2 Harness readiness scorecard

Score each capability 0 (absent) / 1 (observe) / 2 (gate) / 3 (swap):

- [ ] Tool execution — uniform, logged, sandboxed, hookable
- [ ] Model provider — single resolution point, tiered, swappable
- [ ] Credential resolver + vault — referenced by name, redacted, audited
- [ ] Policy / entitlement engine — enforced, tenant-aware, least privilege
- [ ] Evidence / audit — one boundary, stable format, trace ID spans the run
- [ ] Memory & learning — observable writes, consistent recall, prunable
- [ ] Approval / HITL — restart-safe pause/resume, decision flows back, audited
- [ ] Skill router / loader — explainable routing, full package loaded + scoped
- [ ] Scheduler & queue — same capabilities/hooks/gates as chat
- [ ] Lifecycle hooks — documented events, **skill+tool scoping**, fail policy
- [ ] Hard gates — sandbox, path safety, vault, entitlement, mandatory audit
- [ ] Observability — bounded, redacted, read-only inspection of registry + runtime
- [ ] Packaging — install from manifest; refuse on missing *required* capability

A harness scoring mostly 2–3 across these can host portable, governed,
skill-based agents. Gaps at 0–1 on the **hard gates** or **tool execution** rows
are the ones to close first.

---

## One-line summary

> Keep the reasoning core small and general; push *what it knows, what it can do,
> what it's allowed to do, and how it shows results* into portable **skills**; and
> run them on a **harness** that turns every capability into an observable,
> gateable, swappable boundary sitting on top of security gates that can never be
> skipped.

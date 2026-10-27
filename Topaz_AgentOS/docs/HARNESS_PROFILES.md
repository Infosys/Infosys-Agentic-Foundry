# Harness Execution Profiles

A **profile** is a named preset that fills the behavioural harness knobs (verification depth, model
tier, autonomy, budget, learning, durability) so a use-case author picks **one name** instead of
hand-setting a dozen knobs. Profiles are **config, not code** — add or tune one by editing a YAML
file, never a code change.

Full underlying knob catalog: [`HARNESS_CONFIGURATION_CATALOG.md`](HARNESS_CONFIGURATION_CATALOG.md).

## The 5 built-in presets

| Profile | For | verification | model | autonomy | budget | learning |
|---|---|---|---|---|---|---|
| `fast-lookup` | Q&A / status | off | light | confirm | small | off |
| `standard` (default) | most tasks | off | primary | confirm-writes | normal | off |
| `high-assurance` | money / compliance | strict (sufficiency on **primary** verifier + sync critique + consistency) | primary | confirm **(locked)** | normal | off |
| `autonomous` | cron / queue / batch | standard (auto) | primary | unattended (gated) | high deadline | optional |
| `deep-research` | research / long jobs | standard | primary | confirm | **high** tool-calls + long deadline | on + `long-running` |

`standard` is the **parity anchor** — its vector is empty, so a skill with no profile behaves exactly
as before this feature existed.

## How a profile is selected (precedence, request wins)

```
routing_info['profile']  >  skill.profile (SKILL.md)  >  config.yaml default_profile  >
env HARNESS_PROFILE  >  tenant default_profile  >  "standard"
```

- **Per skill:** add `profile: high-assurance` to the SKILL.md frontmatter.
- **Per request:** pass `profile` in the chat payload (WS/HTTP `profile` field) or `agent.run(..., profile=...)`.
- **Per agent (default):** `default_profile:` in the agent `config.yaml`, or the **Admin Settings →
  Harness Profiles** selector (hot-reloads, no restart).

Unknown profile name → warns and falls back to `standard` (never breaks a run).

## Dimensions a profile sets

`verification{enabled,threshold,max_iter,critique_mode,consistency,verifier_model}`, `model_tier`,
`reasoning_effort`, `autonomy{auto_run,locked}`, `budget{max_tool_calls,deadline_seconds}`,
`knowledge_retrieval`, `memory{light_mode}`, `learning{world_model_learn,rl_capture}`,
`duration{interactive|long-running}`.

**Applied today** (per-request, in `agent._apply_profile`): verification (sufficiency loop + critique +
consistency + **primary verifier model**), autonomy (`auto_run`, ratcheted), `light_mode`,
`knowledge_retrieval`, `budget.max_tool_calls` → LangGraph recursion budget. `duration: long-running`
extends the cc_queue skill timeout (`budget.deadline_seconds`). `reasoning_effort` and `engine` are
resolved and logged; full per-request wiring is a follow-up (model registry singleton / dispatch).

## Safety ratchet (one-way)

A dimension section with `locked: true` pins its safety knob to the safe value. Today
`autonomy.locked: true` (in `high-assurance`) forces `auto_run: false` — no derived/tenant profile or
higher layer can loosen it back to unattended execution. `auto_run: true` (autonomous) still passes
through the deterministic dangerous-op HITL gate.

## Maintaining profiles — `harness_profiles.yaml`

Tenant file: `enterprise_root/tenants/<tenant>/config/harness_profiles.yaml`. Overrides/extends the
built-ins; absent file → built-ins only. Hot-reloads on save (cached by mtime).

```yaml
version: "1.0"
default_profile: standard
profiles:
  high-assurance:                 # tune a built-in (only the listed keys change)
    verification: { threshold: 0.92 }
  fraud-review:                   # add a new one; inherit + delta
    extends: high-assurance
    budget: { max_tool_calls: 40, deadline_seconds: 1200 }
    learning: { world_model_learn: true }
```

A skill then selects it with `profile: fraud-review`. Built-in defaults live in
`agentos_contracts/profile.py` (the safe floor; not edited directly).

## Where it lives in code

| Piece | File |
|---|---|
| Contract + resolver + presets + ratchet | `IAF-Agent-Skills/agentos_contracts/profile.py` |
| Tenant YAML loader | `IAF-Agent-Skills/iaf_agent_skills/harness_profiles.py` |
| `profile` skill field | `agentos_contracts/skill.py`, `iaf_agent_skills/loader.py` |
| Runtime application | `iaf_agent_skills/agent.py` (`_apply_profile` / `_restore_profile_overrides`) |
| Chat threading | `IAF-Agent-Studio/routers/chat.py` |
| SKILL.md round-trip | `shared/models.py`, `routers/skills.py`, `routers/personal_skills.py` |
| Long-running timeout | `IAF-Agent-Studio/cc_queue/processor.py` |
| Admin default selector | `IAF-Agent-Studio/routers/settings.py` (`DEFAULT_PROFILE`) |
| Tests | `IAF-Agent-Skills/tests/test_harness_profiles.py` |

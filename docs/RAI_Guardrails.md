# RAI Guardrails

## Overview

IAF integrates **Responsible AI (RAI) Guardrails** to ensure all interactions between users and LLM-powered agents are safe, compliant, and privacy-preserving. The guardrails automatically screen every user input and (optionally) every LLM response for harmful content and sensitive personal information before anything reaches the model or is returned to the user.

Two categories of guardrails are enforced:

| Category | What It Does |
|----------|--------------|
| **Content Moderation** | Detects and blocks jailbreak attempts, toxic language, profanity, and restricted topics |
| **PII Privacy Protection** | Detects personally identifiable information (PII), blocks critical entities, and anonymises the rest before sending to the LLM |

These guardrails are powered by the [Infosys Responsible AI Toolkit](https://github.com/Infosys/Infosys-Responsible-AI-Toolkit) and are transparently integrated — no changes are required to agent configurations or user workflows once enabled.

!!! important "LiteLLM Proxy Required"
    RAI Guardrails are implemented within the **LiteLLM Proxy** layer. To enable or use RAI Guardrails, you **must** set `USE_LITELLM_PROXY_FLAG=true` in your IAF environment configuration. Without this flag, LLM requests bypass the proxy and no guardrail checks will be applied.

---

## Guardrail Checks

### 1. Jailbreak Detection

Identifies attempts to manipulate the LLM into bypassing its safety instructions through prompt injection or jailbreak techniques.

- **What it detects:** Prompt injection patterns, role-play instructions designed to override system prompts, instructions asking the model to ignore previous guidelines
- **Threshold:** Configurable (default: 0.7) — scores at or above this value trigger a block
- **Action on violation:** Request is blocked and the user receives a Content Policy Alert

---

### 2. Toxicity Analysis

Evaluates user input for harmful, hateful, or dangerous language across multiple dimensions.

**Sub-checks include:**

| Sub-check | What It Detects |
|-----------|-----------------|
| General Toxicity | Broadly harmful or negative content |
| Severe Toxicity | Extremely harmful content |
| Obscenity | Obscene or vulgar content |
| Threats | Language indicating intent to harm |
| Insults | Demeaning or degrading language |
| Identity Attacks | Content targeting specific identity groups |
| Sexually Explicit | Inappropriate sexual content |

- **Threshold:** Configurable per sub-check (default: 0.6 for all)
- **Action on violation:** Request is blocked if any sub-check exceeds its threshold

---

### 3. Profanity Filtering

Scans input text for profane or offensive words.

- **What it detects:** Known profane words and phrases in the user's message
- **Threshold:** Number of profane words allowed before triggering (default: 1 — meaning even a single profane word triggers a block)
- **Action on violation:** Request is blocked and flagged words are reported

---

### 4. Restricted Topic Detection

Prevents the LLM from being used to discuss or generate content about topics that your organisation has deemed off-limits.

- **Default restricted topics:** Terrorism, Explosives, Nudity, Cruelty, Cheating, Fraud, Crime, Hacking, Immoral, Unethical, Illegal, Robbery, Forgery, Misinformation
- **Threshold:** Topic relevance score (default: 0.7)
- **Customisable:** Administrators can add or remove topics based on organisational policies
- **Action on violation:** Request is blocked and the detected topic is reported

---

### 5. PII (Personally Identifiable Information) Protection

Automatically detects sensitive personal data in user messages using a RoBERTa NLP model and applies one of three actions per entity type:

| Action | Behaviour | Use Case |
|--------|-----------|----------|
| **Block** | Entire request is rejected | For highly sensitive entities (e.g., email addresses) that should never be sent to an LLM |
| **Anonymise** | Entity is replaced with a placeholder (e.g., `[PHONE_NUMBER_1]`) before sending to the LLM, then restored in the response | For entities that need privacy protection but the conversation should continue |
| **Skip** | Entity is left unchanged | For entities that are acceptable to send to the LLM (e.g., location names, organisation names) |

**Detectable PII entity types include:**

- Email addresses
- Phone numbers
- Credit card numbers
- Social security numbers
- Person names
- Locations
- Dates
- URLs
- Organisation names
- Nationalities / Religious / Political groups (NRP)

The classification of which entities to block, anonymise, or skip is fully configurable via environment variables.

---

## How It Works

**Architecture**

The guardrails operate through a **proxy layer** (LiteLLM Proxy) that sits between IAF and the LLM provider. This architecture ensures guardrails are applied consistently to all agent types without modifying individual agent logic.

```
┌────────────────────┐
│  User sends        │
│  message to agent  │
└────────┬───────────┘
         ▼
┌────────────────────┐
│  IAF Agent         │
│  (any type)        │
└────────┬───────────┘
         ▼
┌────────────────────────────────────────────────────────────┐
│  LiteLLM Proxy — Pre-call Guardrails                        │
│                                                             │
│  Step 1: PII Protection                                     │
│    • Scan for personal information                          │
│    • Block if critical PII found                            │
│    • Anonymise remaining PII with placeholders              │
│                                                             │
│  Step 2: Content Moderation                                 │
│    • Check for jailbreak attempts                           │
│    • Check for toxicity                                     │
│    • Check for profanity                                    │
│    • Check for restricted topics                            │
│    • Block if any check fails                               │
└────────┬────────────────────────────────────────────────────┘
         ▼ (safe, anonymised request)
┌────────────────────┐
│  LLM Provider      │
│  (Azure/OpenAI)    │
└────────┬───────────┘
         ▼ (LLM response)
┌────────────────────────────────────────────────────────────┐
│  LiteLLM Proxy — Post-call Guardrails                       │
│                                                             │
│  Step 3: Response Moderation (optional)                     │
│    • Check LLM output for harmful content                   │
│    • Replace with safe message if violated                  │
│                                                             │
│  Step 4: PII De-anonymisation                               │
│    • Restore original values in place of placeholders       │
└────────┬────────────────────────────────────────────────────┘
         ▼
┌────────────────────┐
│  Response returned  │
│  to user            │
└─────────────────────┘
```

**What Gets Checked**

Only **user-provided content** is moderated. System instructions and framework-generated prompts are excluded from guardrail checks to avoid false positives. The system intelligently identifies user content by looking for specific markers in the message (e.g., "User Query:" or "Input Query:").

**Response Moderation (Optional)**

By default, only user **inputs** are moderated. Optionally, you can also enable **output moderation** to check LLM responses for harmful content. When enabled:

- If the LLM response violates content policy, it is silently replaced with a safe message
- The request is not blocked (since the user's input was fine) — only the response is sanitised

This is recommended for customer-facing applications where LLM output safety is critical.

---

## User Experience

When a guardrail is triggered, the user receives a clear, structured alert explaining what happened:

**Example — Content Policy Violation:**

```
**Content Policy Alert**

Status: FAILED

Check Results:
  ✅ JailBreak — PASSED (score: 0.12, threshold: 0.70)
  ❌ Toxicity — FAILED (score: 0.85, threshold: 0.60)
     • ToxicityScore: 0.85
     • InsultScore: 0.72
  ✅ Profanity — PASSED
  ✅ RestrictTopic — PASSED
```

**Example — PII Privacy Violation:**

```
**Privacy Protection Alert**

Your request was blocked because it contains sensitive personal information:

• EMAIL_ADDRESS detected (confidence: 0.99, position: 10-26)

Entities configured to block: EMAIL_ADDRESS

Please remove the identified information and try again.
```

The guardrail message is returned directly to the user — no further processing or tool calls are attempted once a violation is detected.

---

## Integration with Agent Types

RAI Guardrails are integrated across **all agent types** in IAF. Once enabled, every agent automatically benefits from guardrail protection:

| Agent Type | Guardrail Behaviour |
|------------|-------------------|
| **React Agent** | Catches violations during LLM call, skips tool execution, returns guardrail alert directly |
| **React Critic Agent** | Same as React — violation detected before critic evaluation |
| **Planner Executor Agent** | Scans planner output for violations; catches executor-level violations; early exit on detection |
| **Meta Agent** | Catches violations at sub-agent delegation; skips remaining sub-agents on block |
| **Planner Meta Agent** | Combines planner scanning with meta-agent delegation protection |
| **Hybrid Agent** | Detects violations in agent response and returns formatted alert to user |
| **Workflows** | Each sub-agent within the workflow enforces guardrails independently at its own step |

**Tool Onboarding**

Guardrails also protect the **tool onboarding** process. When new tools are registered, their code is sent through the LLM for validation and documentation generation. If the tool code contains content that violates policy (e.g., references to restricted topics), the onboarding process returns a clear policy-violation message rather than failing silently.

---

## Audit Logging

Every guardrail check (both passes and failures) is logged to a PostgreSQL database for compliance and observability purposes. The audit log captures:

- Timestamp of the check
- Whether it was a pre-call (input) or post-call (output) check
- The content that was moderated
- Overall pass/fail status
- Individual check results and scores (jailbreak, toxicity, profanity, restricted topics)
- PII entities detected and actions taken
- Full API response for debugging

This enables security teams to review moderation activity, identify patterns, and tune thresholds over time.

---

## Failure Handling & Resilience

The guardrails follow a **fail-open** strategy — if the RAI Toolkit APIs are unreachable, requests pass through to the LLM without guardrail protection rather than blocking all traffic. This ensures service availability is not impacted by guardrail infrastructure issues.

| Scenario | Behaviour |
|----------|-----------|
| RAI Moderation API unreachable | Warning logged; request passes to LLM unmoderated |
| PII Analyze API unreachable | Warning logged after retry; request passes without PII protection |
| RAI Moderation returns `PASSED` | Request passes unchanged |
| No PII entities detected | Request passes unchanged |
| Guardrail APIs not configured | Guardrails are skipped entirely |

---

## Configuration

**Enabling Guardrails in IAF**

Set the following environment variables in the IAF `.env` file:

```env
# Route LLM traffic through the proxy (required for guardrails)
USE_LITELLM_PROXY_FLAG=true
LITELLM_ENDPOINT=http://<proxy-host>:<proxy-port>
LITELLM_API_KEY=<api-key>
LITELLM_API_VERSION=<azure-api-version>
LITELLM_MODELS=<comma-separated-model-names>

```

!!! warning
    `USE_LITELLM_PROXY_FLAG=true` must be set for end-to-end guardrail protection. The guardrail type is configured per agent via the **Guardrail Type** dropdown during agent creation.

**Selecting Guardrail Type per Agent**

When creating or onboarding an agent, use the **Guardrail Type** dropdown to select the guardrail checks to apply for that specific agent. The selected guardrail type is sent to the LiteLLM Proxy, which uses a guardrail router to apply the appropriate checks.

!!! Info
    To remove guardrails from an agent, update the agent and select `None` from the `Guardrail Type` dropdown.

**Guardrail Checks for Non-Inference LLM Calls**

To enable guardrail checks for non-inference LLM calls within the framework, navigate to the `Admin Screen`, open the `Config` tab, and select the required guardrail from the `Guardrail` dropdown.

**Configuring the LiteLLM Proxy**

The proxy requires the following environment variables:

| Variable | Description |
|----------|-------------|
| `RAI_API_URL` | URL of the RAI Moderation API |
| `PII_ANALYZE_URL` | URL of the PII Privacy Analyze API |
| `PII_ENTITIES_TO_BLOCK` | Comma-separated PII entity types to hard-block (e.g., `EMAIL_ADDRESS`) |
| `PII_ENTITIES_TO_SKIP` | Comma-separated PII entity types to leave unchanged (e.g., `LOCATION,PERSON,DATE_TIME,NRP,ORGANIZATION,URL`) |
| `DATABASE_URL` | PostgreSQL connection string for audit logging |

**Guardrail Router (LiteLLM Proxy — `server.py`)**

The LiteLLM Proxy implements a `GuardrailRouter` in `server.py` that routes each incoming LLM request to the correct guardrail provider based on the `x-guardrail-provider` HTTP header sent by the IAF server. The header value corresponds to the guardrail type selected for the agent.

- If the header is absent or empty, the request passes through without moderation (equivalent to `guardrail_type = "none"`).
- Currently, the **Infosys RAI** provider is registered by default.
- To integrate a custom guardrail, implement the guardrail service and register it with the router using `guardrail_router.register(...)`.

**Registering a Custom Guardrail**

Call `guardrail_router.register()` with a unique key, the service instance, a display label, and an optional description. Once registered, the new provider appears automatically in the **Guardrail Type** dropdown in the IAF UI.

**Guardrail Registry (IAF Server — `guardrail_helper.py`)**

On startup, the IAF server calls `GuardrailRegistry.sync_from_proxy()` to fetch all registered guardrail providers from the LiteLLM Proxy (`GET /guardrail-providers`). This drives the **Guardrail Type** dropdown in the agent creation/update UI — no hardcoded guardrail types exist in IAF.

- If the proxy is unreachable at startup, the registry stays empty and only `"none"` is valid.
- Any new provider registered in `server.py` is automatically surfaced to the IAF dropdown after a restart.

**Customising Thresholds**

All moderation thresholds are configurable in the proxy's `constants.py` file:

| Check | Default Threshold | Description |
|-------|-------------------|-------------|
| Jailbreak | 0.7 | Score at or above triggers block |
| Prompt Injection | 0.7 | Score at or above triggers block |
| Toxicity (all sub-checks) | 0.6 | Score at or above triggers block |
| Profanity | 1 word | Number of profane words to trigger |
| Restricted Topics | 0.7 | Topic relevance score to trigger |
| PII Detection Confidence | 0.7 | Minimum confidence to consider a PII entity valid |

**Customising Restricted Topics**

Add or remove topics in the `constants.py` configuration:

```python
"Restrictedtopics": [
    "Terrorism", "Explosives", "Nudity", "Cruelty", "Cheating",
    "Fraud", "Crime", "Hacking", "Immoral", "Unethical",
    "Illegal", "Robbery", "Forgery", "Misinformation",
    # Add your custom topics here
]
```

---

## Prerequisites

1. **Infosys RAI Toolkit** — The Moderation and Privacy modules must be deployed on VMs and accessible via HTTP
2. **LiteLLM Proxy** — Must be set up and running with guardrails registered in `config.yaml`
3. **PostgreSQL** — Required for audit logging (shared with IAF's existing database or separate)
4. **Kafka Workers** — Must be running if using guardrails with scheduled (cron) agent executions

---

## Hosting RAI Guardrails on a VM

The RAI Guardrails rely on two open-source modules from the **Infosys Responsible AI Toolkit** — the Moderation Layer and the Privacy module. Both must be deployed and running as HTTP services before IAF can use guardrail protection.

**Modules to Deploy:**

| Module | Purpose | Repository |
|--------|---------|------------|
| **Moderation Layer** | Provides jailbreak detection, toxicity analysis, profanity filtering, and restricted topic checks | [responsible-ai-moderationlayer](https://github.com/Infosys/Infosys-Responsible-AI-Toolkit/tree/master/responsible-ai-moderationlayer) |
| **Privacy Module** | Provides PII detection, entity classification, anonymisation, and de-anonymisation | [responsible-ai-privacy](https://github.com/Infosys/Infosys-Responsible-AI-Toolkit/tree/master/responsible-ai-privacy) |

**Deployment Steps (Summary):**

1. Clone the Infosys Responsible AI Toolkit repository on your VM:
    ```bash
    git clone https://github.com/Infosys/Infosys-Responsible-AI-Toolkit.git
    ```

2. Follow the setup instructions in each module's README:
    - **Moderation Layer:** `responsible-ai-moderationlayer/` — install dependencies, configure models, and start the API server
    - **Privacy Module:** `responsible-ai-privacy/` — install dependencies, configure PII detection models, and start the API server

3. Once both services are running, note their URLs (e.g., `http://<vm-ip>:8081` for moderation, `http://<vm-ip>:8082` for privacy)

4. Configure the LiteLLM Proxy environment variables to point to these services:
    ```env
    RAI_API_URL=http://<vm-ip>:<moderation-port>
    PII_ANALYZE_URL=http://<vm-ip>:<privacy-port>/analyze
    ```

!!! tip "Deployment Recommendations"
    - Deploy both modules on the same VM or within the same network as the LiteLLM Proxy for low-latency checks
    - Ensure the VM has a GPU if you need faster inference for the ML models used in moderation and PII detection
    - Monitor service health and set up restart policies (e.g., via systemd or Docker) to ensure availability

---

## Quick-Start Checklist

1. Deploy the Infosys RAI Toolkit APIs (Moderation + Privacy modules) on VMs
2. Set up the LiteLLM proxy with `.env`, `config.yaml`, and `constants.py`
3. Install proxy dependencies and start the proxy server
4. Configure IAF `.env` with `USE_LITELLM_PROXY_FLAG=true`
5. Restart IAF — all agents will automatically use guardrail protection
6. Verify by sending a test message with known policy-violating content and confirming the guardrail alert is returned

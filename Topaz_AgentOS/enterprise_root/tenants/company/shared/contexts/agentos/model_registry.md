# Model Registry — Multi-Provider, Per-Role

The Model Registry decouples skills from concrete LLM providers. A skill
declares the **role** (`primary`, `light`, `router`, `fallback`); the
registry resolves the role to a configured provider + model.

## Supported providers

| Provider | Auth | Notes |
|---|---|---|
| `azure` | API key + deployment | Default for enterprise (gpt-4o, gpt-5) |
| `openai` | API key | Public OpenAI endpoint |
| `vertex` | Service account JSON | Vertex Gemini 2.5 Pro / Flash (custom adapter for corporate SSL) |

## Roles

- **`primary`** — the main reasoning model (frontier-tier)
- **`light`** — fast/cheap for follow-ups, routing, summarization
- **`router`** — the skill router LLM (often `light`)
- **`fallback`** — only used if primary fails

## Switching providers — one env var

```bash
# In agent_os/config.env
LLM_MODE=vertex          # or 'azure' or 'openai'
```

The four MODE blocks (1=Azure, 2=OpenAI, 3=Azure+OpenAI mix, 4=Vertex)
are pre-wired. Swap providers without touching any SKILL.md.

## Per-skill model override

```yaml
# In SKILL.md frontmatter
model_role: primary       # use primary model
# or
model_role: light         # use the cheaper, faster model
```

## Pricing transparency

Pricing per 1k tokens lives in `agent_os/model_pricing.yaml`. Update
that file and `/finops` recalculates immediately — no code change.

## Vertex Gemini specifics

For corporate networks (Zscaler/Infosys-style):

- Uses service-account JSON + PyJWT (no `gcloud` CLI needed)
- Bundles certifi + system keychain into a combined CA bundle
- Relaxes `VERIFY_X509_STRICT` for corporate cert with non-critical
  Basic Constraints
- File-backed image storage avoids 588K-token prompt bloat

Read more: docs/DEPLOYMENT_GUIDE.md · agent_os/config.env.example

# ContextOS — Enterprise_Context + Taxonomy

ContextOS is the AgentOS layer that decides **which background knowledge
to inject into the prompt** for each user query. It avoids the
"dump-everything" anti-pattern that blows up token budgets.

## The three artifacts

1. **`Enterprise_Context.md`** — tenant-wide root file at
   `enterprise_root/tenants/<tenant>/shared/Enterprise_Context.md`. Lists
   business domains, key entities, taxonomy roots, pointers to deeper
   reference files (the "pillars").

2. **Taxonomy L1–L5 files** — hierarchical reference under
   `shared/contexts/`. Each level adds specificity: L1 = domain, L5 =
   workflow detail. The router scores each level against the user query
   and injects only matching levels.

3. **`context_files:` in SKILL.md** — explicit reusable references the
   skill always wants loaded (e.g. a playbook).

## How it works at request time

```
user query
   │
   ▼
[router] ── taxonomy scoring ──▶ picks skill + relevant L1–L5 context
   │
   ▼
[prompt assembly]   = system prompt
                    + persona (SKILL.md body)
                    + Enterprise_Context.md
                    + matched taxonomy snippets
                    + skill's context_files
                    + conversation history
   │
   ▼
[LLM]
```

## Why it matters

- **Token economy** — only relevant context injected; full taxonomy
  averages ~5–8k tokens but only relevant slice loads per turn.
- **Reuse across skills** — one playbook file feeds many skills.
- **Authoring decoupling** — domain experts edit context files in
  Markdown; engineers never touch them.

## Author once, reference many times

```yaml
# In ar_collections/SKILL.md
context_files:
  - dunning_playbook.md
  - variance_thresholds.md

# In ap_reconciler/SKILL.md
context_files:
  - variance_thresholds.md   # same file, reused
```

Read more: docs/AUTHORING_GUIDE.md · docs/TAXONOMY_AUTHORING.md

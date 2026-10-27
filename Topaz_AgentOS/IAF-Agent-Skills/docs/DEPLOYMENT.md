# IAF Agent Skills Deployment Guide

> **The Golden Reference** - All folder names verified from code analysis on Feb 8, 2026

## Mandatory vs Custom: Quick Reference

| Name | Type | Hardcoded In | Can Rename? |
|------|------|--------------|-------------|
| `tenants` | Folder | kernel.py:369 | ❌ No |
| `agents` | Folder | kernel.py:369 | ❌ No |
| `shared` | Folder | kernel.py:370 | ❌ No |
| `users` | Folder | kernel.py:446 | ❌ No |
| `memory` | Folder | kernel.py:420 | ❌ No |
| `SKILL.md` | File | loader.py:97 | ❌ No |
| `_index.yaml` | File | router.py:43 | ❌ No |
| `DATA_ROOT` | Env | server.py:60 | ✅ Yes |
| `SKILLS_PATH` | Env | server.py:61 | ✅ Yes |
| `{tenant_id}` | Folder | Uses variable | ✅ Yes |
| `{agent_id}` | Folder | Uses variable | ✅ Yes |
| `{user_id}` | Folder | Uses variable | ✅ Yes |
| Skill folders | Folder | Dynamic from filesystem | ✅ Yes |

---

## Required Folder Structure

```
{DATA_ROOT}/                          # Set via environment variable
└── tenants/                          # MANDATORY - hardcoded
    └── {your_tenant_id}/             # CUSTOM - from API calls
        ├── agents/                   # MANDATORY - hardcoded
        │   └── {your_agent_id}/      # CUSTOM - from API calls
        │       ├── users/            # MANDATORY - hardcoded
        │       │   └── {user_id}/    # CUSTOM - populated at runtime
        │       │       └── (user files here)
        │       └── memory/           # MANDATORY - hardcoded
        │           └── agent_memory.json
        └── shared/                   # MANDATORY - hardcoded
            └── (shared read-only files)

{SKILLS_PATH}/                        # Set via environment variable
└── {skill-folder-name}/              # CUSTOM - your choice
    └── SKILL.md                      # MANDATORY - must be this exact name
```

---

## Environment Configuration

Create a `.env` file or export these variables:

```bash
# Required - paths to your data
export DATA_ROOT="/path/to/your/data"
export SKILLS_PATH="/path/to/your/skills"

# Optional - server settings
export PORT=8080
export HOST=0.0.0.0
```

---

## Step-by-Step Deployment

### 1. Create the folder structure

```bash
# Set your paths
DATA_ROOT="/your/data/path"
TENANT_ID="acme_corp"
AGENT_ID="finance_agent"

# Create mandatory folders
mkdir -p "$DATA_ROOT/tenants/$TENANT_ID/agents/$AGENT_ID/users"
mkdir -p "$DATA_ROOT/tenants/$TENANT_ID/agents/$AGENT_ID/memory"
mkdir -p "$DATA_ROOT/tenants/$TENANT_ID/shared"
```

### 2. Create skills folder

```bash
SKILLS_PATH="/your/skills/path"

# Create skill folders (names are your choice)
mkdir -p "$SKILLS_PATH/invoice-processor"
mkdir -p "$SKILLS_PATH/email-triage"
```

### 3. Add SKILL.md files

Each skill folder MUST contain a file named exactly `SKILL.md`:

```markdown
# Invoice Processor

Description of what this skill does...

## Instructions
...
```

### 4. Create _index.yaml (optional but recommended)

In your `SKILLS_PATH`, create `_index.yaml`:

```yaml
skills:
  - name: invoice-processor
    description: Processes incoming invoices
    triggers:
      - invoice
      - payment
  - name: email-triage
    description: Categorizes and routes emails
    triggers:
      - email
      - message
```

### 5. Start the server

```bash
export DATA_ROOT="/your/data/path"
export SKILLS_PATH="/your/skills/path"
python3 server.py
```

---

## Virtual Path Mapping (How SafeKernel works)

When users reference files in conversations:

| User Types | Maps To | Access |
|------------|---------|--------|
| `/me/report.xlsx` | `{agent_root}/users/{user_id}/report.xlsx` | Read/Write |
| `/shared/template.docx` | `{agent_root}/../shared/template.docx` | Read Only |
| `~/notes.txt` | `{agent_root}/users/{user_id}/notes.txt` | Read/Write |

---

## Common Mistakes to Avoid

1. **Wrong:** Naming folder `tenant` instead of `tenants` (plural)
2. **Wrong:** Creating `user` instead of `users` (plural)  
3. **Wrong:** Naming skill file `skill.md` instead of `SKILL.md` (case matters)
4. **Wrong:** Writing to `/shared/` - it's read-only
5. **Wrong:** Omitting `_index.yaml` - skill routing won't work optimally

---

## Verification Checklist

```bash
# Verify folder structure
ls -la $DATA_ROOT/tenants/*/agents/*/users/
ls -la $DATA_ROOT/tenants/*/shared/

# Verify skills
ls -la $SKILLS_PATH/*/SKILL.md

# Verify index
cat $SKILLS_PATH/_index.yaml
```

---

## Code References

These are the exact lines where folder names are hardcoded:

**kernel.py (SafeKernel):**
```python
# Line 369
self.agent_root = self.data_root / "tenants" / tenant_id / "agents" / agent_id

# Line 370  
self.shared_path = self.data_root / "tenants" / tenant_id / "shared"

# Line 446
self.agent_root / "users"

# Line 420
self.agent_root / "memory"
```

**loader.py:**
```python
# Line 97
skill_file = skill_folder / "SKILL.md"
```

**router.py:**
```python
# Line 43
self.index_path = self.skills_path / "_index.yaml"
```

---

*Generated from code analysis - Last verified: Feb 8, 2026*

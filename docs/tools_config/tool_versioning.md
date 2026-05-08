# Tool Versioning

The Tool Versioning system provides comprehensive version control for tools. It enables tracking of code changes, safe rollbacks, import/export with version preservation, and soft-delete with recovery capabilities.

---

## Version Creation

- When a tool is onboarded, an initial version `v1` is created automatically.
- Each tool version is saved as `{tool_name}_{version}.py` (e.g., `calculator_v1.py`).

## Version Update

When editing a tool, you can choose to:

- **Update existing version** — Overwrite the code of a specific version (e.g., update `v1` in place).
- **Create new version** — Generate a new version (e.g., `v2`, `v3`) while preserving the previous one. The new version number equals `MAX(existing versions) + 1`.

## Version Numbering Rules

- Format: `v{N}` (e.g., `v1`, `v2`, `v3`)
- Gaps are allowed — if `v1` and `v3` exist (with `v2` deleted), the next version is `v4`
- Version numbers are never reused

---

## Version Creation Flow

=== "Tool Creation"

    When a tool is onboarded (`POST /tools/generate/onboard` or `POST /tools/upload`):

    1. Tool record is created in `tool_table`
    2. Initial `v1` is created automatically in `tool_versions_table`
    3. Python file is saved as `{tool_name}_v1.py`

=== "Update — Overwrite Version"

    To overwrite the code of an existing version:

    ```json
    {
      "version": "v1",
      "code_snippet": "..."
    }
    ```

    **Result:** `v1` code is overwritten in place. No new version is created.

=== "Update — Create New Version"

    To preserve the existing version and create a new one:

    ```json
    {
      "create_new_version": true,
      "code_snippet": "..."
    }
    ```

    **Result:** New version created (e.g., `v2`, `v3`).  
    Version number = `MAX(existing) + 1`.  
    New file saved as `{tool_name}_{new_version}.py`.

---

## Version Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/tools/{tool_id}/versions` | List all version strings for a tool |
| `GET` | `/tools/{tool_id}/versions/{version}` | Get specific version code and details |
| `PUT` | `/tools/edit/{tool_id}` | Update existing version or create a new one |
| `DELETE` | `/tools/{tool_id}?version=v2` | Soft-delete a specific version |
| `DELETE` | `/tools/{tool_id}` | Soft-delete the entire tool and all its versions |

!!! note
    A version cannot be deleted if it is the last remaining version of a tool. Delete the entire tool instead.

## Version Recycle Bin

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/tools/recycle-bin/versions/{tool_id}` | View deleted versions for a specific tool |
| `GET` | `/tools/recycle-bin/versions` | View all deleted versions |
| `POST` | `/tools/recycle-bin/versions/restore/{tool_id}/{version}` | Restore a deleted version |
| `DELETE` | `/tools/recycle-bin/versions/permanent-delete/{tool_id}/{version}` | Permanently delete (irreversible, Admin only) |

**Restore Behaviour:** If the original version number already exists (e.g., `v2` was re-created after deletion), the restored version is assigned a new number (`MAX + 1`) automatically.

---

## Recycle Bin & Recovery

=== "Delete Version"

    ```
    DELETE /tools/{tool_id}?version=v2
    ```

    1. Check: Is this the last version? → Error if yes
    2. Get version data from `tool_versions_table`
    3. Move to `recycle_tool_versions` (preserves all data)
    4. Delete from `tool_versions_table`
    5. Delete file `{tool_name}_v2.py`

    !!! info
        The version can be restored later from the recycle bin.

=== "Delete Tool"

    ```
    DELETE /tools/{tool_id}
    ```

    1. Check dependencies (agents using this tool)
    2. Move **all** versions to `recycle_tool_versions`
    3. Move tool record to `recycle_tool` table
    4. Delete from `tool_table` (CASCADE deletes versions)
    5. Delete all version files

    !!! info
        The tool and all its versions can be restored together.

=== "Restore Version"

    ```
    POST /tools/recycle-bin/versions/restore/{tool_id}/{version}
    ```

    1. Get version data from `recycle_tool_versions`
    2. Check: Does version number already exist?
        - **YES** → Assign new version number (`MAX + 1`)
        - **NO** → Use original version number
    3. Create record in `tool_versions_table`
    4. Recreate file `{tool_name}_{version}.py`
    5. Delete from `recycle_tool_versions`

---

## Import / Export with Versioning

**Export Structure**

When exporting tools, each version is exported as a separate file:

```
export_package/
├── tools/
│   ├── calculator/
│   │   ├── calculator_v1.py
│   │   ├── calculator_v2.py
│   │   ├── calculator_v3.py
│   │   └── metadata.json
│   └── string_helper/
│       ├── string_helper_v1.py
│       └── metadata.json
└── manifest.json
```

**Import Conflict Resolution**

When importing a tool that already exists in the target system:

| Conflict Type | Resolution |
|---------------|------------|
| Same tool name exists | `create_new_tool`, `create_new_version`, or `skip` |
| Same version exists | Auto-renamed to the next available version number |
| Identical code (duplicate) | Skipped automatically using hash comparison |

---

## Agent–Tool Version Binding

Agents are bound to **specific versions** of each tool. This ensures an agent always runs with a known, tested version of the tool code.

**Example agent tool configuration:**
```json
{
  "tools_with_versions": [
    {"tool_id": "tool-abc", "tool_version": "v2"},
    {"tool_id": "tool-def", "tool_version": "v1"}
  ]
}
```

To update which version an agent uses, update the agent's tool version binding:
```json
{
  "tool_versions": {
    "tool-abc": "v3",
    "tool-def": "v2"
  }
}
```

---

## Version Conflict Resolution

| Scenario | Automatic Handling |
|----------|-------------------|
| Create new version when MAX is v5 | Creates v6 |
| Restore v2 when v2 already exists | Restores as v6 (MAX+1) |
| Import v3 when v3 already exists | Skips or creates v4 based on setting |
| Delete v2 when only v2 exists | Error: Cannot delete last version |

---

## Permissions

| Operation | Who Can Perform |
|-----------|----------------|
| View versions | Any authenticated user |
| Create new version | Tool creator or Admin |
| Update existing version | Tool creator or Admin |
| Delete version | Tool creator or Admin |
| Restore version | **Admin only** |
| Permanent delete | **Admin only** |

---

## Best Practices

**DO:**

- Use **create new version** for significant code changes
- Add a meaningful description when creating a new version
- Test a new version by binding it to a test agent before updating production agents
- Export tools with all versions before making major changes

**DON'T:**

- Delete versions that are bound to active agents
- Overwrite a version without understanding the impact on agents using it
- Use version update when you should create a new version

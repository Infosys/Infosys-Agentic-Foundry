# Tool & MCP Server Export / Import

Export and import lets you share **Tools** and **MCP Servers** between environments or team members using `.zip` files. Select the tools or servers you want to export, download a ZIP, and import it into another environment. The system automatically handles naming conflicts, duplicate detection, version management, and validation.

---

## Overview

| | Tools | MCP Servers |
|---|---|---|
| **What gets exported** | Python code files (`.py`) + metadata (`.json`) | Configuration files (`.json`), plus code files (`.py`) for file-based servers |
| **What you upload to import** | A `.zip` containing `.py` files (and optionally metadata `.json`) | A `.zip` containing `.json` config files (and `.py` for file-based servers) |
| **Name conflicts** | You choose: create with a new name, add as a new version, or skip | Automatic: the system appends `_copy1`, `_copy2`, etc. |
| **Duplicate handling** | Identical tools are auto-skipped | Identical servers are auto-skipped |
| **Version support** | Yes — previous versions are exported and imported alongside the main code | No |
| **Docstring** | If your tool code is missing a docstring, one is generated automatically | N/A |

---

!!! Info "Who Can Use This"

    - **Admins** and **Developers** can export and import tools and MCP servers.
    - Export requires **read** permission on tools within your department.
    - Import requires **create** permission on tools within your department.
    - Imported tools/servers are automatically assigned to **your department**.
    - The same tool name can exist independently in different departments — there is no cross-department conflict.

## Tool Export

When you export tools, you receive a `.zip` file. For each tool, the ZIP contains:

| File | Purpose |
|---|---|
| `tool_name.py` | The main Python code of the tool (latest version) |
| `tool_name_v1.py`, `tool_name_v2.py`, ... | Code for each saved version (if versions exist) |
| `tool_name_metadata.json` | Metadata describing the tool and its version history |

**Sample Exported ZIP**

```
tools_export.zip
├── calculate_sum.py
├── calculate_sum_v1.py
├── calculate_sum_v2.py
├── calculate_sum_metadata.json
├── fetch_weather.py
└── fetch_weather_metadata.json
```

**Sample Tool Code File (`calculate_sum.py`)**

```python
def calculate_sum(a: int, b: int) -> int:
    """
    Calculates the sum of two integers.

    Args:
        a: The first integer.
        b: The second integer.

    Returns:
        The sum of a and b.
    """
    return a + b
```

**Sample Metadata File (`calculate_sum_metadata.json`)**

```json
{
  "tool_name": "calculate_sum",
  "tool_description": "Calculates the sum of two integers.",
  "model_name": "gpt-4",
  "created_by": "alice@example.com",
  "main_code_file": "calculate_sum.py",
  "versions": [
    {
      "version": "v1",
      "filename": "calculate_sum_v1.py",
      "tool_description": "Initial version"
    },
    {
      "version": "v2",
      "filename": "calculate_sum_v2.py",
      "tool_description": "Added input validation"
    }
  ]
}
```

---

## Tool Import

Upload a `.zip` file containing `.py` files. Each `.py` file should have a single Python function — this becomes one tool.

You can also include `_metadata.json` files if you want to import version history alongside the main code. If no metadata file is present, the system creates a default first version automatically.

**Sample Input ZIP**

```
my_tools.zip
├── calculate_sum.py
├── fetch_weather.py
└── greet_user.py
```

Each `.py` file must contain a valid Python function, for example:

```python
def greet_user(name: str) -> str:
    return f"Hello, {name}!"
```

**What Happens During Import**

The system processes each `.py` file and checks whether a tool with the same name already exists in your department:

| Scenario | What Happens |
|---|---|
| **New tool** (name doesn't exist) | Imported directly. If the function has no docstring, one is generated automatically using the selected LLM model. |
| **Same name, same code** | Skipped — the tool already exists with identical code. Any new versions from the ZIP are still imported if they contain different code. |
| **Same name, different code** | **You choose** what to do (see below). |
| **Name exists in recycle bin** | You are asked to provide a new name for the tool. |

**Handling Name Conflicts**

When a tool with the same name but different code exists, you have three options:

1. **Create as new tool** — Provide a new name for the imported tool. The function in the code is automatically renamed to match.
2. **Add as new version** — The imported code is added as a new version (e.g., v3) to the existing tool. The main tool code stays unchanged.
3. **Skip** — Do not import this tool.

**Name rules:**

- Names ending with `_v1`, `_v2`, etc. are **reserved** for version files and cannot be used as tool names.
- The new name must not already exist in your department's tools or recycle bin.
- If you provide an invalid name, the system tells you what's wrong so you can correct it — no tools are imported until all names are valid.

**Import Preview**

Before actually importing, you can preview what will happen. The preview analyzes the ZIP and tells you:

- Which tools will be imported directly (new, no conflict).
- Which tools will be skipped (identical code already exists).
- Which tools have conflicts that need your decision.

This lets you review everything before any changes are made.

**What You Get After Import**

A summary showing:

- **Imported** — Tools successfully created, with their new names if renamed.
- **Merged** — Tools where imported code was added as a new version to an existing tool.
- **Skipped** — Tools that already existed with the same code.
- **Failed** — Tools that couldn't be imported (with the reason).
- **Versions imported** — Version files that were successfully added.

---

## MCP Server Export

When you export MCP servers, you receive a `.zip` file. The contents depend on the server type:

| Server Type | Files in ZIP |
|---|---|
| **File-based** (`file`) | `server_name.json` (metadata) + `server_name.py` (the server's Python code) |
| **URL-based** (`url`) | `server_name.json` (metadata with URL and headers) |
| **Module-based** (`module`) | `server_name.json` (metadata with module name and command) |

**Sample Exported ZIP**

```
mcp_servers_export.zip
├── my_data_processor.json       # File-type server metadata
├── my_data_processor.py         # File-type server code
├── external_api_server.json     # URL-type server metadata
└── playwright_server.json       # Module-type server metadata
```

**Sample JSON Files**

**File-type server** (`my_data_processor.json`):

```json
{
  "tool_name": "my_data_processor",
  "tool_description": "Custom MCP server for processing data files",
  "mcp_type": "file"
}
```

The actual server code is in the companion file `my_data_processor.py`.

**URL-type server** (`external_api_server.json`):

```json
{
  "tool_name": "external_api_server",
  "tool_description": "Connects to an external API",
  "mcp_type": "url",
  "mcp_url": "https://mcp.example.com/sse",
  "headers": {
    "Authorization": "VAULT::MY_API_KEY",
    "Content-Type": "application/json"
  }
}
```

!!! Note 
    Header values starting with `VAULT::` are references to secrets stored in the vault. The actual secret values are **not** included in the export. After importing, you will need to set up matching vault entries in your environment.

**Module-type server — Python** (`my_python_mcp.json`):

```json
{
  "tool_name": "my_python_mcp",
  "tool_description": "MCP server via a Python package",
  "mcp_type": "module",
  "mcp_module_name": "my_mcp_package",
  "mcp_command": "python"
}
```

**Module-type server — npx** (`playwright_server.json`):

```json
{
  "tool_name": "playwright_server",
  "tool_description": "Browser automation via Playwright MCP",
  "mcp_type": "module",
  "mcp_module_name": "@playwright/mcp@latest",
  "mcp_command": "npx"
}
```

The `mcp_command` field indicates how the module is launched:

| Command | Meaning |
|---|---|
| `python` | Runs the module with `python -m module_name` |
| `npx` | Runs the module with `npx -y module_name` |
| Other (e.g., `node`) | Uses the specified command directly |

If `mcp_command` is not specified, `python` is assumed by default.

---

## MCP Server Import

Upload a `.zip` file containing `.json` configuration files (one per MCP server). For file-type servers, include the companion `.py` file with the same name.

**Sample Input ZIP**

```
my_servers.zip
├── my_data_processor.json
├── my_data_processor.py         # Required for file-type servers
├── external_api_server.json
└── playwright_server.json
```

Each `.json` file must include at minimum:

- `tool_name` — The server name.
- `mcp_type` — One of `file`, `url`, or `module`.
- Type-specific fields (`mcp_url` for URL-type, `mcp_module_name` for module-type, companion `.py` file for file-type).

**What Happens During Import**

| Scenario | What Happens |
|---|---|
| **New server** (name doesn't exist) | Imported directly with the original name. |
| **Same name, same configuration** | Skipped — the server already exists with an identical setup. |
| **Same name, different configuration** | Imported with an auto-generated name: `server_name_copy1`, `server_name_copy2`, etc. |
| **Name exists in recycle bin** | Imported with an auto-generated copy name. |

**What counts as "same configuration"** depends on the server type:

| Server Type | Compared Fields |
|---|---|
| `file` | The Python code content |
| `url` | The URL and headers |
| `module` | The module name and command (e.g., `python` vs `npx`) |

The server description is **not** considered when checking for duplicates — only the functional configuration matters.

**What You Get After Import**

A summary showing:

- **Imported** — Servers successfully created (with the renamed name if a copy was made).
- **Skipped** — Servers that already existed with the same configuration.
- **Failed** — Servers that couldn't be imported (with the reason, e.g., missing `.py` companion file for a file-type server, invalid JSON, or failed security validation).

---

## Department Isolation

Tools and MCP servers are scoped to your department:

- The **same name** can exist in different departments without conflict.
- When you import, conflicts are only checked against tools/servers **in your own department**.
- Public tools from other departments do **not** cause naming conflicts.
- Everything you import is automatically assigned to your department.

??? Example 
    If the Engineering department has a tool called `calculator` and you (in the Marketing department) import a ZIP containing `calculator.py`, there is no conflict — Marketing gets its own `calculator` tool.

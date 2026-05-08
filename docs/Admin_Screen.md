# Admin Screen 
## Overview
The `Admin Screen` serves as the central hub for managing and monitoring key components of the system. 

- It is organized into multiple sections including `chat`, `Tools`, `Servers`, `Agents`, `Workflows`, `Vault`, `Data Connectors`, `Knowledge Base`, `Resource Dashboard`, `Evaluation`, `Files` and an additional tab labeled `Admin`. 
- The `Admin` tab is specifically designed to provide administrators with advanced management capabilities.
- Within the `Admin` tab, you will find four main functional tabs that enable administrators to effectively manage users, oversee agent feedback, Installation, recycle bin management and Unused tools and agents, Groups and Role Control, Resource Management, and Inference Configuration.
---

## 1. User Management

The User Management section in the Admin tab allows administrators to manage user accounts, roles, and access within their department. Admins have three key capabilities:

- **User Assignment** — Assign roles to registered users within the department. SuperAdmin can assign any role in any department, while Admin can only assign roles within their own department.
- **User Update** — Update a user's role, or reset/set a temporary password for users within the department.
- **User Access Management** — Enable or disable login access for users. Admins can manage users within their own department, while SuperAdmin can manage users globally across all departments.

For detailed information on user management operations, permissions, and rules, refer to the RBAC documentation:

[:octicons-arrow-right-24: User Management Within Departments](RBAC.md#5-user-management-within-departments)


## 2. Learning - Feedback Approval

This tab centralizes feedback management for all agents in the system, enabling admins to review and validate user feedback to improve agent responses.

Learning - Feedback Approval is a feature designed to help administrators manage, evaluate, and improve the performance of agents through structured feedback. It acts as a centralized hub where all feedback related to the agents' responses is collected and analyzed. The primary goal is to enhance the quality and accuracy of the agents’ replies by reviewing and applying feedback provided by users or evaluators.

In this system, admins can view all the agents deployed in the platform. By selecting a specific agent, they can access all the feedback associated with that agent. This feedback can include evaluations of how well the agent answered specific queries, suggestions for improvement, or issues with the agent's responses.

The system offers a comprehensive view of each feedback item. For each feedback, admins can see:

- The original query from the user, which provides context for understanding the issue or request the agent was addressing.

- The original response from the agent, showing how the agent initially handled the query.

- Feedback and updates, which include comments or suggestions from users or evaluators regarding the agent’s response, helping admins understand what needs to be improved.

- A new final response, which is the updated version of the agent’s answer after incorporating feedback. This step ensures that the agent's future responses are more accurate and relevant.

- A detailed record of the conversation steps, including the interaction history, tools used, and the context of the conversation, providing deeper insight into the agent's decision-making process.

- `Lesson`: The lesson summarizes the LLM's understanding and learning based on the provided feedback. Admins can view, edit, and update the lesson as needed. By enabling the "Included in learning" toggle, the admin approves the lesson. If the lesson is unsatisfactory, the admin can revise it before approval.

!!! Info
    The Learning - Feedback Approval process is essential for continuously refining the agent's performance. By regularly reviewing and applying feedback, admins can ensure that the agents become more capable, accurate, and responsive over time, leading to improved user satisfaction and efficiency.


**Administrative Capabilities:**

- Review the feedback in detail to assess its validity and impact on agent performance.
- Approve the lesson by enabling the **"Included in learning"** toggle switch. This marks the feedback as approved and ready to be integrated into the agent's learning.
- Commit changes, which updates the agent's knowledge base or response logic accordingly.
- This process supports continuous learning and improvement of agents by integrating verified feedback.

---

## 3. Installation

The `Installation` tab provides administrators with comprehensive visibility into the Python package dependencies required by the tools in the system. This section helps ensure that all necessary packages are properly installed and tracks pending installation requests from users.

### Missing Dependencies

This tab identifies Python packages that are required by existing tools but are not currently installed in the environment.

**How It Works:**

- The system extracts all tool code snippets from the database for existing tools.
- It parses the import statements from each tool's code to identify all referenced modules.
- User-defined modules and Python standard library (stdlib) packages are filtered out.
- The remaining packages are identified as real PyPI packages.
- These identified packages are compared against: `requirements.txt` file and currently installed packages in the environment.
- Any packages that are not installed are listed under `Missing Dependencies`.

!!! Info "Admin Action"

    - Review the list of missing packages.
    - Install the required packages to ensure all tools function correctly.

---

### Installed Dependencies

This tab displays all Python packages currently installed in the environment.

**How It Works:**

- The system runs a subprocess command to list all installed packages.
- The complete list of installed packages with their versions is displayed to the administrator.

!!! info "Use Case"

    - Verify that required packages are installed.
    - Check package versions for compatibility.
    - Audit the environment for security or compliance purposes.

---

### Pending Dependencies

This tab tracks tool onboarding failures caused by missing module dependencies and displays them for admin review.

**How It Works:**

- During tool onboarding, the system validates that all imported modules in the tool code are available.
- If a module is not found, the tool onboarding is blocked with a "module not found" validation error.
- The system records the following details in the database:
   - `Module Name:` The missing package/module that caused the failure.
   - `Tool Code:` The tool code snippet that contains the import.
   - `User:` The user who attempted to onboard the tool.
- These pending dependency requests are displayed to the administrator under this tab.

!!! info "Admin Action"

    - Review pending dependency requests from users.
    - Install the requested packages after validation.
    - Notify users once the package is installed so they can retry tool onboarding.

## 4. RecycleBin

The **RecycleBin** tab lets administrators manage deleted tools, agents and MCP Servers. All removed items are listed here, providing a way to review them before permanent deletion.

**Key Features**

- **View Deleted Items:** See a list of all deleted tools, agents and MCP Servers.
- **Restore Functionality:** Restore mistakenly deleted items with a single click.

    > Restore Conflict Handling

    When restoring an item, the system checks whether an item with the same name already exists in the main database. The behavior differs by resource type:

    **Tools — Restore Conflict**

    If a tool with the same name already exists in the main database, the system detects a conflict and presents two options:

    1. **Add as new version** — The restored tool's code is added as a new version to the existing tool that shares the same name.
    2. **Restore as new tool** — The tool is restored under a different name. The admin is prompted to provide a new name before the restore proceeds.

    **Agents — Restore Conflict**

    If an agent with the same name already exists in the main database, the admin is prompted to provide a new name. The agent is then restored under the new name.

    **MCP Servers — Restore Conflict**

    If an MCP server with the same name already exists in the main database, the admin is prompted to provide a new name. The server is then restored under the new name.

- **Permanent Deletion:** Permanently remove items that are no longer needed. This action cannot be undone.

!!! Note
    Only users with administrative privileges can access the RecycleBin tab and perform restore or permanent delete actions.

## 5. Unused Tools, Agents and MCP Servers

The **Unused Tools, Agents and MCP Servers** tab displays all tools, agents and MCP Servers that have not been used or updated in the last 15 days. `Unused` means there has been no interaction with the agent or modification to the tool/agent during this period.

**Administrative Capabilities:**

- View a comprehensive list of unused tools, agents and MCP Servers.
- Delete unused tools, agents or MCP Servers directly from this tab.
- Deleted items are automatically moved to the RecycleBin for potential recovery or permanent deletion.

## 6. Control Tab

The **Control** tab in the Admin section enables administrators to manage groups and configure role-based permissions within their department.

**Group Management** — Organize users and agents into groups for collaborative access and shared vault secrets. Admins can create, update, and manage group memberships within their department.

**Role Permissions** — Configure role-based access control by defining what actions each role can perform on resources (Tools, Agents, Servers, Workflows). Set Read, Add, Update, Delete, and Execute permissions at the role level.

For detailed information on group creation, member management, permission configuration, and access control rules, refer to the RBAC documentation:

[:octicons-arrow-right-24: Group Management](RBAC.md#group-management)

[:octicons-arrow-right-24: Permissions](RBAC.md#permissions)

---

## 7. Resource Management

The `Resource Management` section in the Admin tab enables administrators to control tool-level data access across the organization. This feature provides fine-grained access control by allowing tool creators to define access keys that determine which data users can access when running specific tools.

**Key Capabilities:**

- `Access Key Management` — Create, view, and manage access keys that control data access at the tool level
- `Resource Allocation` — Assign and manage access key permissions for users within the department
- `User Access Control` — Define allowed or excluded values for each user, supporting both specific values and wildcard access patterns
- `Tool Integration` — View which tools are using specific access keys and manage their associations
- `Bulk User Management` — Efficiently add or remove multiple users from access keys

**Admin Responsibilities:**

1. View all access keys created within their department
2. Manage user assignments to access keys
3. Update user-specific allowed/excluded values for fine-grained control
4. Monitor which users have access to specific data resources
5. Ensure proper data access governance and compliance

For detailed information on access key creation, resource allocation workflows, tool-level decorators, and comprehensive examples, refer to the RBAC documentation:

[:octicons-arrow-right-24: Resource Dashboard](RBAC.md#resource-dashboard)

## 8. Inference Configuration

The **Inference Configuration** section in the Admin tab allows administrators to configure and manage inference-related settings for the system. This section provides control over how agents process queries and generate responses, enabling fine-tuning of performance, behavior, and resource utilization.

**Key Configuration Options:**

Administrators can manage various inference parameters that affect agent behavior and performance:

- **Model Selection** — Configure which language models are available for different agent types and use cases
- **Temperature Settings** — Adjust the randomness and creativity of agent responses
- **Token Limits** — Set maximum token counts for prompts and responses to control costs and response length
- **Timeout Configuration** — Define timeout thresholds for inference requests to prevent long-running operations
- **Retry Logic** — Configure retry attempts and backoff strategies for failed inference calls
- **Streaming Settings** — Enable or disable streaming responses for real-time user feedback
- **Caching Policies** — Set up response caching to improve performance and reduce API costs
- **Rate Limiting** — Configure rate limits to prevent system overload and manage API quotas

**Admin Capabilities:**

- View current inference configuration settings across the system
- Update configuration parameters to optimize agent performance
- Set department-specific or global inference policies
- Monitor inference behavior and adjust settings based on usage patterns
- Ensure compliance with organizational policies and budget constraints

!!! tip "Best Practices"
    - Start with conservative settings and adjust based on monitoring data
    - Test configuration changes in a development environment before applying to production
    - Balance response quality with cost and performance considerations
    - Regularly review and optimize settings based on user feedback and system metrics

## 9. Multiple Deletion

Administrators have the exclusive ability to **select and delete multiple items at once** across all major resource sections of the platform. This capability is not available to Developers, Users, or any other role.

!!! warning "Admin-Exclusive Feature"
    Multiple deletion is available **only for the Admin role**. Other roles (Developer, User) can only delete items one at a time using the standard per-item delete action.

**Supported Sections**

Multiple deletion is available in the following sections:

<div class="grid cards" markdown>

- :material-wrench: **Tools**
- :material-check-circle: **Validators**
- :material-server: **Servers**
- :material-robot: **Agents**
- :material-pipe: **Workflows**
- :material-safe: **Vault**
- :material-book-open: **Knowledge Bases**
- :material-text-search: **Consistency**
- :material-view-dashboard: **Resource Dashboard**
- :material-tools: **Unused Tools**
- :material-robot-off: **Unused Agents**
- :material-server-off: **Unused Servers**
- :material-account-group: **Groups Management** *(inside a group)*
- :material-file-multiple: **Files**

</div>

**How It Works**

**1. Selecting Items**

- A checkbox appears next to each item in the list — only visible to Admin users.
- Admins can select individual items or use a **Select All** checkbox to select every item on the current list.
- The count of selected items is displayed in the action bar.

**2. Triggering Multiple Delete**

- Once one or more items are selected, a **Delete Selected** button becomes active in the action bar.
- Clicking it opens a confirmation dialog listing the selected items before proceeding.

**3. Validation**

- All existing validation checks are applied to each item before deletion — the same checks used for single item deletion.
- If an item cannot be deleted (e.g., a tool is currently bound to an agent, or an agent is bound to a workflow), that item is skipped with an appropriate error message, and the rest of the valid items are deleted.

**4. Recycle Bin**

- Deleted items follow the **same recycle bin flow** as single item deletion — they are moved to the RecycleBin and are not permanently removed immediately.
- Items remain in the RecycleBin for 30 days and can be restored by an Admin before permanent deletion.

!!! note
    Multiple deletion does not bypass any existing safeguards. Every item goes through the same pre-deletion validation and post deletion recycle flow as individual deletions — the only difference is that multiple items can be selected and processed in a single action.

---

## 10. Backup & Cleanup Guide

This guide explains how to use the `Backup` and `Cleanup` features in the IAF. Both operations are restricted to `Admin` users only.

### Backup Functionality

The backup feature extracts all agents, tools, validators, MCP servers, and workflows from the IAF database and pushes the data to a configured GitHub repository. This allows teams to maintain a versioned, off-database copy of all platform resources.

Each backup run is organised under a folder named after the server (using the `SERVER_NAME` environment variable) inside the configured GitHub repository.

---

**What Gets Backed Up**

| Category | Contents |
|---|---|
| **Agents** | Agent configurations (`agent_config.json`), tags, type, model bindings, tool bindings |
| **Tools** | Tool code (`.py`), tool config (`config.json`), all historical versions under a `versions/` subfolder |
| **Validators** | Same structure as tools; identified by tool IDs starting with `_validator` |
| **MCP Servers** | MCP server configs (`mcp_config.json`) and extracted server code (`.py`) |
| **Workflows** | Workflow definitions (`workflow_config.json`) along with embedded agent data |

---

**Prerequisites Before Running a Backup**

Before triggering a backup you **must** ensure the following secrets are configured in the application's secrets store:

| Secret Key | Description |
|---|---|
| `GITHUB_USERNAME` | GitHub username of the account that will push the backup |
| `GITHUB_PAT` | GitHub Personal Access Token (PAT) with **write** access to the target repository |
| `GITHUB_EMAIL` | Email address associated with the GitHub account |
| `TARGET_REPO_NAME` | Name of the target GitHub repository where backups will be stored |
| `TARGET_REPO_OWNER` | Owner (user or organisation) of the target GitHub repository |

!!! Important
    The PAT must have at least `repo` scope to allow pushing new branches to the target repository. If the token has expired or lacks write access, the backup will fail with a clear error message.

Additionally, the `SERVER_NAME` environment variable must be set in your deployment, as it is used to name the backup folder inside the repository.

---

**How to Trigger a Backup**

The backup is triggered via a REST API call:

**Endpoint:**
```
POST /utility/backup-and-export
```

**Request Body:**
```json
{
  "user_email": "admin@example.com"
}
```

**Authentication:** The request must be made by a logged-in `Admin` user. Provide the session cookie in the request.

**What happens after you call this endpoint:**

1. The system extracts all agents, tools, validators, MCP servers, and workflows from the database into a temporary folder.
2. The extracted data is pushed to the configured GitHub repository as a new branch, under a path scoped to the server name.
3. The temporary local folder is cleaned up automatically after the push.
4. A response is returned with the GitHub URL of the pushed backup.

**Successful Response:**

```json
{
  "success": true,
  "message": "Backup completed and pushed to GitHub repository: <owner>/<repo>",
  "github_url": "<URL to the pushed branch>",
  "server_name": "<SERVER_NAME>",
  "repository": "<owner>/<repo>"
}
```

---

**Backup Output Structure**

Inside the GitHub repository, the backup is organised as follows:

```
<SERVER_NAME>/
├── Agents/
│   ├── <Tag_or_General>/
│   │   └── <AgentName>/
│   │       └── agent_config.json
├── Tools/
│   └── <ToolName>/
│       ├── config.json
│       ├── <ToolName>.py
│       └── versions/
│           ├── v1.py
│           ├── v2.py
│           └── ...
├── Validators/
│   └── <ValidatorName>/
│       ├── config.json
│       ├── <ValidatorName>.py
│       └── versions/
├── MCP_Servers/
│   └── <Tag_or_General>/
│       └── <McpServerName>/
│           ├── mcp_config.json
│           └── <McpServerName>.py
└── Workflows/
    └── <WorkflowName>/
        └── workflow_config.json
```

- **Agents** are grouped by their assigned tag (domain/category). Untagged agents fall under `General/`.
- **Tools and Validators** include all historical versions under a `versions/` subfolder.
- **MCP Servers** are grouped by tag similar to agents.

---

**Common Backup Errors**

| Error Message | Likely Cause | Resolution |
|---|---|---|
| `GitHub authentication failed. Please verify your GitHub Personal Access Token (PAT)...` | PAT is expired or has insufficient scope | Regenerate the PAT with `repo` scope and update the secret |
| `Access denied to GitHub repository...` | Insufficient permissions on the repository | Ensure the account has write access to the target repository |
| `GitHub repository not found...` | Incorrect `TARGET_REPO_NAME` or `TARGET_REPO_OWNER` | Verify and correct the values in secrets |
| `No data found to backup...` | No agents, tools, or other resources exist in the database | Add at least one resource before backing up |
| `Unable to clean up temporary directory...` | File lock on the temp folder from a previous run | Wait a moment and try again |

---

### Cleanup Functionality

The cleanup feature identifies and removes `test, demo, sample, and orphan` resources from the IAF database. It follows a `two-step process`: first preview what will be deleted, then execute the deletion. This ensures nothing is removed without admin awareness.

Both steps generate downloadable Excel reports for auditing purposes.

---

**What Gets Cleaned Up**

The cleanup targets the following resource types:

- **Agents** (including Meta Agents and Workflow Agents)
- **Tools** (regular tools and validators)
- **MCP Tools / Servers**
- **Workflows**

---

**Cleanup Criteria**

A resource is flagged for cleanup if it meets `one or both` of the following conditions:

**1. Test/Demo/Sample Name Pattern**

The resource name contains any of the following words as whole words or separated by common delimiters (`_`, `-`, space):

| Matched Words |
|---|
| `test`, `demo`, `sample`, `example`, `dummy` |
| `trial`, `mock`, `fake`, `tmp`, `temp` |
| `untitled`, `foo`, `bar`, `hello`, `world` |
| `experiment`, `playground`, `scratch`, `sandbox` |

!!! Info
    Resources created by the system (`created_by = 'system'`) are **excluded** from cleanup.

**2. Orphan**

A resource is considered an orphan when it is not bound to or used by any other resource (e.g., a tool not used by any agent, or an agent not part of any meta agent or workflow).

---

**Step 1 – Preview Cleanup**

Use this step to review what would be deleted **before** making any changes.

**Endpoint:**
```
POST /utility/cleanup/preview
```

**Request Body:**

```json
{
  "send_emails": false
}
```

Set `send_emails` to `true` if you want the system to send notification emails to the creators of the identified resources (requires Outlook to be configured on the server).

**What this returns:**

- A count summary of items found per category (agents, tools, workflows, MCP tools)
- Path to a generated preview Excel report (`CLEANUP_PREVIEW_<timestamp>.xlsx`) stored in the `cleanup_reports/` folder
- Number of emails sent (if `send_emails` was `true`)

**Example Response:**

```json
{
  "status": "success",
  "message": "Found 12 items for cleanup",
  "summary": {
    "agents": 5,
    "tools": 4,
    "workflows": 2,
    "mcp_tools": 1,
    "total": 12
  },
  "report_file": "cleanup_reports/CLEANUP_PREVIEW_20260429_103045.xlsx",
  "emails_sent": 3
}
```

!!! Info "Recommendation"
    Always run a preview first and download the report to review the items before proceeding to execution.

---

**Step 2 – Execute Cleanup**

Once you have reviewed the preview and are confident about proceeding, execute the cleanup.

**Endpoint:**
```
POST /utility/cleanup/execute
```

**Request Body:** None required.

**What happens:**

1. The system re-fetches all items matching cleanup criteria at the time of execution.
2. Tools are unbound from agents before deletion.
3. Agents are unbound from meta agents and workflows before deletion.
4. All matched items are permanently deleted from the database.
5. A deletion report (`DELETION_REPORT_<timestamp>.xlsx`) is generated and stored in the `deletion_reports/` folder.
6. A download URL for the deletion report is returned.

**Example Response:**

```json
{
  "status": "success",
  "message": "Successfully deleted 12 items",
  "deleted_counts": {
    "agents": 5,
    "tools": 4,
    "workflows": 2,
    "mcp_tools": 1
  },
  "related_cleanup": {
    "tool_agent_unbindings": 8,
    "agent_meta_unbindings": 2
  },
  "report_download_url": "/utility/cleanup/report/download/DELETION_REPORT_20260429_103120.xlsx"
}
```

!!! Note
    Execution is permanent. Deleted items cannot be recovered from this flow. Ensure you have reviewed the preview report before proceeding.

---

**Downloading Cleanup Reports**

Both preview and deletion reports can be downloaded using:

**Endpoint:**
```
GET /utility/cleanup/report/download/{filename}
```

Replace `{filename}` with the exact filename returned in the preview or execute response (e.g., `CLEANUP_PREVIEW_20260429_103045.xlsx`).

The file is returned as an Excel (`.xlsx`) download.

---

**Listing All Reports**

To see a list of all available preview and deletion reports:

**Endpoint:**
```
GET /utility/cleanup/reports/list
```

This returns filenames from both `cleanup_reports/` and `deletion_reports/` folders.

---
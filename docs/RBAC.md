# Role-Based Access Control (RBAC)

## Overview

The Infosys Agent Foundry (IAF) implements a comprehensive **Role-Based Access Control (RBAC)** system that governs access to all platform resources. The system is organized around `departments`, where each department has its own set of `roles` and `permissions`, providing fine-grained control over who can view, create, update, delete, and execute tools, agents, workflows, and other resources.

**Key Principles**

- `Department-scoped access`: Users see and interact only with resources in their department (plus shared/public resources).
- `Role-based permissions`: Each role within a department has a configurable permission matrix.
- `Hierarchical authority`: SuperAdmin > Admin > Developer > User.
- `Cross-department sharing`: Resources can be made public or shared with specific departments.
- `Cascade sharing`: Sharing an agent or workflow automatically shares its dependent resources.
- `Audit trail`: Every action is logged for security and compliance.
- `Notification-driven approvals`: New user registrations trigger notification emails to department admins and SuperAdmin for approval. 

---

## Architecture

**1. Departments**

Departments are the `top-level organizational unit`. Every resource (tools, agents, MCP servers, workflows, knowledge bases, etc.) belongs to a department, and users operate within the context of a department.

- A `default "General" department` is automatically created on first server startup.
- Only the `SuperAdmin` can create or delete departments.
- Each department maintains its own allowed roles and corresponding permissions.
- When a new department is created, three `default roles` are automatically added: `Admin`, `Developer`, and `User` — each with pre-configured default permissions.
- The `Admin` role `cannot be deleted` from any department.

**2. Roles**

Roles define the level of access a user has within a department.

| Role | Description |
|------|-------------|
| `SuperAdmin` | Platform-wide access. Not tied to any single department. Centralized control over all departments. |
| `Admin` | Highest authority within a department. Manages users, roles, permissions, groups, and resources within their own department. Cannot be deleted from any department.|
| `Developer` | Full CRUD and execute access on tools, agents, and workflows within their department. |
| `User` | Read and execute access on agents and workflows only (by default). |

!!! Note
    A member can hold **one or more roles per department** and may also have accounts in **multiple departments**. When a user has multiple roles in the same department, exactly one role is **active** at a time, and the user can **switch** between their assigned roles.

**3. Role Hierarchy**

```
SuperAdmin (Level 3) ──── Platform-wide, all permissions
    │
    ├── Admin (Level 2) ──── Department-wide, manages users/roles/permissions
    │       │
    │       ├── Developer (Level 1) ──── Full CRUD + Execute on tools, agents, workflows
    │       │
    │       └── User (Level 0) ──── Read + Execute agents/workflows only
    │
    └── (Can manage any department)
```

---

## Authentication

**1. Registration**

-  Users register with `email`, `username`, and `password`, and `department` (or a list of departments).
-  Upon registration, a `notification` in Admin/SuperAdmin tab and an `email` is automatically sent to the `Admin(s)` of the selected department(s) and the `SuperAdmin`.
-  The user remains in a `pending` state until an Admin or SuperAdmin approves them.
-  Admin or SuperAdmin approves the user by `assigning a role` in that department via the `Notifications tab`. An email will be sent to the user upon approval.
-  `Multiple approvals` can be processed at a time — admins can approve several pending users in bulk.
-  Once approved with a role, the user can log in.

**2. Notifications Tab**

A dedicated `Notifications tab` is available for `Admin` and `SuperAdmin` users.

- When a new user registers and selects a department, a notification appears in the Notifications tab for the department's Admin(s) and the SuperAdmin.
- From this tab, Admin/SuperAdmin can `approve` the user by assigning them a role in the department.
- Multiple pending user approvals can be handled at once.
- SuperAdmin receives notifications for registrations across `all departments`.
- Admin receives notifications only for their `own department`.
- Registration requests are retrieved through a `paginated search` and are **sorted by creation time** for predictable ordering.

**3. Login**

-  Users log in with `email`, `password`, and `department`.
-  Department selection is `required` for all users except SuperAdmin.
-  SuperAdmin can log in `with or without` specifying a department (department is optional for SuperAdmin).
-  Users must have `active status` to log in (both globally and within the department).

**4. Request Department Access**

After logging in, users can request access to additional departments from the `Requests tab`.

- Any authenticated user can submit a request to join another department.
- The request is sent to the `Admin(s)` of the target department and the `SuperAdmin` for review.
- Admins review and approve or reject requests via the `Notifications tab`.
- Upon approval, the user is assigned a role in the requested department.

**5. SuperAdmin Bootstrap (First-Time Setup)**

When the platform has `no SuperAdmin` or `no users exist` in the database:

-  The registration page automatically becomes a `SuperAdmin registration`.
-  The user provides `email`, `username`, and `password` only (no department selection).
-  This user is registered as the `SuperAdmin` with platform-wide access.
-  The default `"General"` department is created automatically with default roles:
   - `Admin` — Full permissions within department + Admin Tab
   - `Developer` — Full permissions within department
   - `User` — Agent read + execute only

**6. Password Management**

| Feature | Description |
|---------|-------------|
| `Reset Password` | SuperAdmin can set a temporary password for any user across all departments. Admin can set a temporary password for users within their own department. The temporary password must then be shared with the user so they can log in. |
| `Forced Password Change` | On the next login with the temporary password, the user is required to set a new password before they can proceed. |
| `Self-Service Change` | Any authenticated user can change their own password at any time. |

---

## Department Management

### 1. Default Department

- `Name`: `General`
- `Auto-created` on server startup.
- `Default roles`: Admin, Developer, User (with pre-configured default permissions for each).
- The `Admin` role cannot be deleted from any department.

### 2. Department Operations

| Operation | Who Can Do It | Description |
|-----------|---------------|-------------|
| `Create Department` | SuperAdmin only | Creates a new department. |
| `Delete Department` | SuperAdmin only | Deletes a department and its associations. |
| `List Departments` | Any authenticated user | View all available departments. |
| `Get Department Details` | Any authenticated user | View specific department information. |


### 3. Role Management Within Departments

| Operation | Who Can Do It | Description |
|-----------|---------------|-------------|
| `Add Role to Department` | Admin (own dept) / SuperAdmin | Adds an allowed role (Admin/Developer/User) to a department. Default permissions are auto-assigned. |
| `Remove Role from Department` | Admin (own dept) / SuperAdmin | Removes a role from a department. **Admin role cannot be removed.** |
| `List Department Roles` | Admin (own dept) / SuperAdmin | View all roles configured for a department. |

!!! Warning
    The **Admin** role is a protected default role and **cannot be deleted** from any department.

### 4. Default Roles on Department Creation

When a new department is created, the following roles are automatically provisioned with default permissions:

| Role | Auto-Created | Can Be Deleted |
|------|:------------:|:--------------:|
| `Admin` | ✅ | ❌ (Protected) |
| `Developer` | ✅ | ✅ |
| `User` | ✅ | ✅ |

### 5. User Management Within Departments

Admins have three categories of user management (accessible from the `Admin Tab`):

**User Update**:

- Update a user's role within the department.
- Reset/set temporary password for users.
- SuperAdmin can operate across all departments.

**User Access Management**:

- `Enable/disable` login access for users.
- Admin can disable users `within their own department only`.
- Users `cannot disable themselves`.
- Admin `cannot disable SuperAdmin` users.

**SuperAdmin User Management Enhancements**

- **Flat user listing** — SuperAdmin sees a consolidated list of all users across all departments in a single view, rather than having to switch between departments individually.
- **Departments dropdown with "All" option** — The department filter dropdown includes an "All" option for SuperAdmin, allowing them to view users from every department at once. The dropdown uses a search-enabled paginated endpoint for efficient lookup.
- **Department name on user cards** — Each user card displays the department name, providing clear context about which department each user belongs to when viewing the cross-department list.
- **Department-wise `is_active` control** — The global `is_active` flag has been removed. User access is now controlled at the department level with a department-specific `is_active` flag, enabling finer-grained access control. A user can be active in one department while being disabled in another.

**Multi-Role Support & Role Switching**

A user can be assigned **more than one role within the same department**, allowing a single account to carry different levels of access (for example, `Developer` and `Admin`) without needing separate accounts.

- **Multiple roles per department** — Admins (own department) and SuperAdmin can assign several roles to a user in a department. A single role-update request can **add and remove multiple roles** at once.
- **Active role & switching** — When a user holds multiple roles, one role is **active** at a time. The user can switch their active role, and the platform applies the permissions of the newly selected role for subsequent actions.
- **Remove a role** — Admins (own department) and SuperAdmin can remove one or more roles from a user, subject to the usual authorization checks. The protected `Admin` role rules still apply.
- **Retrieve a user's roles** — A dedicated endpoint returns all roles a user holds in a specific department, with role-based access control enforced on the request.
- **SuperAdmin role management** — SuperAdmin can manage roles for any user across all departments.
- **Audit trail** — Role switches are recorded in the audit trail, and the user's current active role can be retrieved at any time.

---

## Permissions

**1. Permission Matrix**

Each role within a department has a configurable permission matrix:

**CRUD & Execute Permissions (Resource-Level)**

Each of the following permissions can be toggled independently for `Tools`, `Agents`,  `MCP Servers` and `workflows`:

| Permission | Controls |
|------------|----------|
| `Read Access` | View resource details |
| `Add Access` | Create new resources |
| `Update Access` | Modify existing resources |
| `Delete Access` | Delete resources |
| `Execute Access` | Execute/run resources |

!!! Note
    `MCP Servers` and `Workflows` each have their own **separate permission set** — they no longer inherit permissions from Tools or Agents. `Export Agents` access is a standalone toggle permission.

**Chat/Execution Toggle Permissions**

These control features within the agent chat/execution interface:

| Permission | Description | Dependency |
|------------|-------------|------------|
| `Execution Steps` | View detailed execution steps | Requires `Execute Access (Agents)` |
| `Tool Verifier` | Tool verifier toggle in chat | Requires `Execute Access (Agents)` |
| `Plan Verifier` | Plan verifier toggle in chat | Requires `Execute Access (Agents)` |
| `Online Evaluation` | Online evaluation toggle | Requires `Execute Access (Agents)` |
| `Validator` | Validator tools access | Requires `Execute Access (Agents)` |
| `File Context` | File context management | Requires `Execute Access (Agents)` |
| `Canvas View` | Canvas view in UI | Requires `Execute Access (Agents)` |
| `Context` | Context management | Requires `Execute Access (Agents)` |

**Import, Export & Convert Permissions**

These permissions control import/export of tools and MCP servers, as well as the ability to convert tools to MCP servers:

| Permission | Description | Dependency |
|------------|-------------|------------|
| `Export Tools Access` | Export tools from the platform | None |
| `Export Servers Access` | Export MCP servers from the platform | None |
| `Import Tools Access` | Import tools into the platform | Requires `Add Access (Tools)` |
| `Import Servers Access` | Import MCP servers into the platform | Requires `Add Access (MCP Servers)` |
| `Import Agents Access` | Import agents into the platform | Requires `Add Access (Agents)` |
| `Convert to MCP Access` | Convert a tool to an MCP server | Requires `Add Access (MCP Servers)` |

!!! note "Import & Convert Dependencies"
    - **Import Tools** can only be enabled when the corresponding **Add Access (Tools)** permission is enabled.
    - **Import MCP Servers** can only be enabled when **Add Access (MCP Servers)** is enabled.
    - **Import Agents** can only be enabled when **Add Access (Agents)** is enabled.
    - **Convert to MCP** can only be enabled when **Add Access (MCP Servers)** is enabled.

    Action buttons for Import, Export, and Convert are shown in the UI only when the respective permission is granted.

**Independent Permissions**

These permissions are standalone and do not depend on other permissions:

| Permission | Description |
|------------|-------------|
| `Evaluation Access` | Access to evaluation features |
| `Vault Access` | Access to secrets/vault management |
| `Data Connector Access` | Access to data connector features |
| `Knowledge Base Access` | Access to knowledge base management |
| `Export Agents Access` | Access to export agent features |

**Special Permissions (Implied)**

| Permission | Dependent On |
|------------|-------------|
| `Resource Dashboard` | Requires `Add Access (Tools)` or `Update Access (Tools)` |

**2. Permission Dependencies**

```
Read Access (Tools) ◄── Add Access (Tools)
                    ◄── Update Access (Tools)
                    ◄── Delete Access (Tools)
                    ◄── Execute Access (Tools)

Read Access (Agents) ◄── Add Access (Agents)
                     ◄── Update Access (Agents)
                     ◄── Delete Access (Agents)
                     ◄── Execute Access (Agents) ◄── Execution Steps
                                                  ◄── Tool Verifier
                                                  ◄── Plan Verifier
                                                  ◄── Online Evaluation
                                                  ◄── Validator
                                                  ◄── File Context
                                                  ◄── Canvas View
                                                  ◄── Context
Read Access (MCP Servers) ◄── Add Access (MCP Servers) ◄── Import Servers Access
                          ◄── Update Access (MCP Servers)         ◄── Convert to MCP Access
                          ◄── Delete Access (MCP Servers)
                          ◄── Execute Access (MCP Servers)

Add Access (Tools) ◄── Import Tools Access
Add Access (MCP Servers) ◄── Import Servers Access
                         ◄── Convert to MCP Access

Read Access (Workflows) ◄── Add Access (Workflows)
                        ◄── Update Access (Workflows)
                        ◄── Delete Access (Workflows)
                        ◄── Execute Access (Workflows)
```

**Validation Rule**: `Read Access` is a `prerequisite` — you cannot grant `Add`, `Update`, `Delete`, or `Execute` access for a resource type unless `Read Access` is enabled for that same resource type.

**3. Default Permissions by Role**

When a role is added to a department, default permissions are auto-assigned:

=== "Tools Permissions"

    | Permission | Admin | Developer | User |
    |------------|:-----:|:---------:|:----:|
    | Read Access | ✅ | ✅ | ❌ |
    | Add Access | ✅ | ✅ | ❌ |
    | Update Access | ✅ | ✅ | ❌ |
    | Delete Access | ✅ | ✅ | ❌ |
    | Execute Access | ✅ | ✅ | ❌ |

=== "Agents Permissions"

    | Permission | Admin | Developer | User |
    |------------|:-----:|:---------:|:----:|
    | Read Access | ✅ | ✅ | ✅ |
    | Add Access | ✅ | ✅ | ❌ |
    | Update Access | ✅ | ✅ | ❌ |
    | Delete Access | ✅ | ✅ | ❌ |
    | Execute Access | ✅ | ✅ | ✅ |

=== "MCP Servers Permissions"

    | Permission | Admin | Developer | User |
    |------------|:-----:|:---------:|:----:|
    | Read Access | ✅ | ✅ | ❌ |
    | Add Access | ✅ | ✅ | ❌ |
    | Update Access | ✅ | ✅ | ❌ |
    | Delete Access | ✅ | ✅ | ❌ |
    | Execute Access | ✅ | ✅ | ❌ |

=== "Workflows Permissions"

    | Permission | Admin | Developer | User |
    |------------|:-----:|:---------:|:----:|
    | Read Access | ✅ | ✅ | ✅ |
    | Add Access | ✅ | ✅ | ❌ |
    | Update Access | ✅ | ✅ | ❌ |
    | Delete Access | ✅ | ✅ | ❌ |
    | Execute Access | ✅ | ✅ | ✅ |

=== "Chat / Execution Toggles"

    | Permission | Admin | Developer | User |
    |------------|:-----:|:---------:|:----:|
    | Execution Steps | ✅ | ✅ | ❌ |
    | Tool Verifier | ✅ | ✅ | ❌ |
    | Plan Verifier | ✅ | ✅ | ❌ |
    | Online Evaluation | ✅ | ✅ | ❌ |
    | Validator | ✅ | ✅ | ❌ |
    | File Context | ✅ | ✅ | ❌ |
    | Canvas View | ✅ | ✅ | ❌ |
    | Context | ✅ | ✅ | ❌ |

=== "Independent Permissions"

    | Permission | Admin | Developer | User |
    |------------|:-----:|:---------:|:----:|
    | Evaluation Access | ✅ | ✅ | ❌ |
    | Vault Access | ✅ | ✅ | ❌ |
    | Data Connector Access | ✅ | ✅ | ❌ |
    | Knowledge Base Access | ✅ | ✅ | ❌ |
    | Export Agents Access | ✅ | ✅ | ❌ |
    | Export Tools Access | ✅ | ✅ | ❌ |
    | Export Servers Access | ✅ | ✅ | ❌ |

**4 Managing Permissions**

| Operation | Who Can Do It | Restriction |
|-----------|---------------|-------------|
| `Set permissions`  | Admin (own dept) / SuperAdmin | Admin `cannot` modify Admin role permissions |
| `View permissions` | Admin (own dept) / SuperAdmin | Admin sees own dept only; SuperAdmin sees all |

!!! Important "Critical Rule"
    Only **SuperAdmin** can set or update permissions for the **Admin** role. Department Admins cannot modify their own role's permissions.

---

## Sharing Across Departments

Resources can be shared with other departments using the `Share button` available on resource cards (Tools, MCP Servers, Agents, Workflows, Knowledge Bases).

**1. Public Access**

Marking a resource as `Public` makes it `visible and read-accessible` to `all departments`.

- Available for: `Tools`, `MCP Servers`, `Agents`, `Workflows`, `Knowledge Bases`.
- Use the `Share button` on any resource card and select `Make Public`.

**2. Department-Specific Sharing**

Using the `Share button`, a resource can be shared with `specific departments` only.

- Available for: `Tools`, `MCP Servers`, `Agents`, `Workflows`, `Knowledge Bases`.
- Use the `Share button` on any resource card and select the target department(s).
- `Public` and `Shared with Departments` are `mutually exclusive` — a public resource is already accessible to all, so specifying departments is redundant.

**3. Sharing Operations**

**Agent Sharing**

| Operation | Description |
|-----------|-------------|
| `Share Agent` | Share an agent with specific departments via the Share button. |
| `Unshare Agent` | Remove sharing of an agent from a specific department. |
| `View Sharing Info` | View the current sharing configuration for an agent. |
| `View Shared Agents` | View agents that have been shared with the current user's department. |

**Workflow Sharing**

| Operation | Description |
|-----------|-------------|
| `Share Workflow` | Share a workflow with specific departments via the Share button. |
| `Unshare Workflow` | Remove sharing of a workflow from a specific department. |
| `View Sharing Info` | View the current sharing configuration for a workflow. |
| `View Shared Workflows` | View workflows that have been shared with the current user's department. |

**Tool & MCP Server Sharing**

Sharing is managed via the `Share button` on Tool and MCP Server cards, allowing you to make them public or share with specific departments.

**Knowledge Base Sharing**

| Operation | Description |
|-----------|-------------|
| `Share Knowledge Base` | Share a knowledge base with specific departments via the Share button. |
| `Update KB Sharing` | Update the sharing settings for a knowledge base. |
| `Upload KB with Sharing` | Upload a knowledge base with sharing options configured. |

---

## Group Management

**1. Groups Overview**

Groups provide a way to organize `users` and `agents` within a department for collaborative access — particularly for shared secrets in the vault.

- Groups are `department-scoped`: all members and agents must belong to the `same department`.
- Only `Admins` can create and manage groups within their own department.

**2. Group Operations**

- `Admin` can create a group within their department, adding users and agents to it.
- `Admin` can update group members, agents, and description, or delete the group entirely.
- `Admin` can look up which groups a specific user or agent belongs to.

**3. Group Secrets (Vault)**

Groups can have their own `secrets` stored in the vault, accessible only by group members. This is available in the `Vault` page under the `Group Keys` tab.

- `Anyone` can create, update, and delete group secrets (requires `Vault Access` permission).
- `Group members` can view the secrets of their group (requires `Vault Access` permission).
- Users who are not members of the group cannot see or manage its secrets.

!!! Note
    All group secret operations require the `Vault Access` permission to be enabled for the user's role.

---

## Resource Dashboard

The Resource Dashboard provides `tool-level data access control` — allowing tool creators to define access keys that control which data a user can access when running a tool.

**1. Access Key Management (Self-Service)**

Available to users with `tool create/update permission`:

| Operation | Description |
|-----------|-------------|
| `List Access Keys` | View all access keys in the department |
| `Create Access Key` | Create a new access key |
| `Get Access Key Details` | View details of a specific access key |
| `Delete Access Key` | Delete an access key (creator, or any Admin in the department) |
| `View Tools Using Key` | View which tools are using a specific access key |
| `Update Own Access` | Update own allowed/excluded values for an access key |

`Key Rules:`

- The `creator` of an access key can delete it. `Admins` can delete any access key in their department **without the creator check**.
- Cannot delete an access key if tools are still using it.
- Access keys are returned through a `paginated search`, ordered by creation time, so large sets of keys page predictably.
- Supports `wildcard` access: `allowed_values: ["*"]` with optional `exclusions: ["CEO001"]`.
- Wildcard (`*`) and specific values are `mutually exclusive`.

**2. Resource Allocation (Admin)**

Admins can manage access key assignments for users in their department:

| Operation | Description |
|-----------|-------------|
| `List Access Keys` | View all access keys in the admin's department |
| `View Key Users` | View which users have access to a specific key |
| `View User's Values` | View a specific user's allowed values for a key |
| `Update User's Access` | Update a user's access values for a key |
| `Bulk Manage Users` | Bulk add or remove users from a key |

**3. Tool-Level Access Decorators**

Tool creators can embed access control directly in tool code using three decorators:

**`@resource_access(access_key, param_name)` — Data-Level Access Control**

Checks if the executing user has permission to access specific data values based on their access key assignments.

```python
@resource_access("employee_access", "employee_id")
def get_employee_salary(employee_id: str):
    # Only runs if user has access to this employee_id
    ...
```

**`@require_role(*roles)` — Role-Based Access Control**

Restricts tool execution to users with specific roles.

```python
@require_role("Admin", "Developer")
def admin_only_tool():
    # Only runs for Admin or Developer users
    ...
```

**`@authorized_tool` — Combined Access Control**

Combines both resource access and role-based checks.

```python
@authorized_tool
def combined_access_tool():
    # Both role and resource access checks applied
    ...
```

These decorators use a `ToolUserContext` that is automatically injected at runtime, containing:
- `user_id`, `email`, `role`, `department`, `token`
- `resource_access`: Dictionary of access key → allowed values
- `resource_exclusions`: Dictionary of access key → excluded values

---

## Dynamic UI Visibility

The UI dynamically shows or hides `tabs and features` based on the logged-in user's permissions.

**Resource Cards Visibility**

All resource cards (`Tools`, `Agents`, `MCP Servers`, `Workflows`, `Knowledge Bases`) are `visible to all users` on the UI regardless of their permissions. However, users can only `view the data inside` a resource card when they have `Read Access` for that resource type. Without Read Access, the card is visible but the detailed content within is restricted.

**Tab & Feature Visibility**

| UI Element | Required Permission |
|------------|-------------------|
| `Tools tab` | Read Access (Tools) |
| `Agents tab` | Read Access (Agents) |
| `Servers tab` | Read Access (MCP Servers) |
| `Workflows tab` | Read Access (Workflows) |
| `Export Agents tab` | Export Agents Access |
| `Export Tools` | Export Tools Access |
| `Export Servers` | Export Servers Access |
| `Import Tools` | Import Tools Access |
| `Import Servers` | Import Servers Access |
| `Convert to MCP` | Convert to MCP Access |
| `Evaluation tab` | Evaluation Access |
| `Vault tab` | Vault Access |
| `Data Connectors tab` | Data Connector Access |
| `Knowledge Base tab` | Knowledge Base Access |
| `Resource Dashboard` | Add Access (Tools) or Update Access (Tools) |
| `Admin tab` | Admin or SuperAdmin role |
| `Notifications tab` | Admin or SuperAdmin role |
| `Requests tab` | Any authenticated user |
| `Execution Steps (chat)` | Execution Steps |
| `Tool Verifier (chat)` | Tool Verifier |
| `Plan Verifier (chat)` | Plan Verifier |
| `Online Evaluation (chat)` | Online Evaluation |
| `Validator (chat)` | Validator |
| `File Context (chat)` | File Context |
| `Canvas View (chat)` | Canvas View |
| `Context (chat)` | Context |
| `Permissions page` | Available in Profile tab for all authenticated users |

Users will `only see` the tabs and features they have permission for. The permissions page in the Profile tab allows any logged-in user to view their own permission set.

---

## SuperAdmin TTL Cleanup

SuperAdmin has access to a dedicated endpoint for `manual data cleanup (TTL)` across the platform.

| Feature | Description |
|---------|-------------|
| `Manual TTL Cleanup` | SuperAdmin can trigger a manual cleanup of old chat histories across `all departments`. |
| `Scope` | Cleans up expired/old chat history data for every department in the platform. |
| `Access` | Available to `SuperAdmin only`. |

This provides SuperAdmin with direct control over data retention and storage management without waiting for automated TTL expiration processes.

---

## Files & File Context

The platform supports two levels of file storage:

| Level | Scope | Access |
|-------|-------|--------|
| `Root-level files` | Global | Accessible by `all departments` |
| `Department-level files` | Department-scoped | Accessible by `department members only` |

File context access is controlled by the `File Context` permission.

---

## Business Rules Summary

**SuperAdmin Rules**

- When no SuperAdmin exists or no users are in the database, the registration page becomes a SuperAdmin registration (email, username, password only).
- Has platform-wide access — all permission checks return `true`.
- Can log in without specifying a department.
- Can create/delete departments.
- Can assign any role in any department.
- Can disable users globally.
- Is the only role that can modify Admin role permissions.
- Can manually trigger TTL cleanup of old chat histories across all departments.
- Cannot create or update groups (not tied to any department).

**Admin Rules**

- Highest authority within their own department.
- Can manage users, roles, and permissions in their department only.
- Cannot modify Admin role permissions — only SuperAdmin can.
- Cannot delete the Admin role from any department.
- Cannot disable SuperAdmin users.
- Cannot disable themselves.
- Receives notifications when new users register for their department.

**Registration & Approval Rules**

- Users register with email, username, password, and department(s).
- Registration sends a notification to the selected department's Admin(s) and SuperAdmin.
- Admin/SuperAdmin approves users by assigning a role in the department via the Notifications tab.
- Multiple user approvals can be processed at a time.
- Users remain in a pending state until approved.

**Department Rules**

- When a new department is created, default roles (`Admin`, `Developer`, `User`) are automatically added.
- The `Admin` role is protected and cannot be deleted from any department.

**Sharing Rules**

- A `Share button` is available on resource cards (Tools, MCP Servers, Agents, Workflows, Knowledge Bases) for sharing to specific departments or making public.
- `Public` and `Shared with Departments` are mutually exclusive.
- Shared resources provide read-only access to target departments.

**Permission Rules**

- `Read` permission is a prerequisite for `Create`, `Update`, `Delete`, and `Execute` permissions.
- Chat toggle permissions (Execution Steps, Tool Verifier, etc.) require `Execute Agents` permission.
- `MCP Servers` and `Workflows` each have their own separate permission sets. `Export Agents` access is a standalone toggle.
- Resource Dashboard requires tool create/update permission.
- Vault operations require `Vault Access` permission.
- Resource cards are visible to all users; Read Access controls whether users can view the data inside.

**Tool/Agent Update Rules**

- Tools and MCP servers bound to an agent cannot be updated — must remove from agent first.
- Agents bound to a workflow cannot be updated independently.

---
# Role-Based Access Control (RBAC)

## Overview

The Infosys Agent Foundry (IAF) implements a comprehensive **Role-Based Access Control (RBAC)** system that governs access to all platform resources. The system is organized around `departments`, where each department has its own set of `roles` and `permissions`, providing fine-grained control over who can view, create, update, delete, and execute tools, agents, pipelines, and other resources.

**Key Principles**

- `Department-scoped access`: Users see and interact only with resources in their department (plus shared/public resources).
- `Role-based permissions`: Each role within a department has a configurable permission matrix.
- `Hierarchical authority`: SuperAdmin > Admin > Developer > User.
- `Cross-department sharing`: Resources can be made public or shared with specific departments.
- `Cascade sharing`: Sharing an agent or pipeline automatically shares its dependent resources.
- `Audit trail`: Every action is logged for security and compliance.

---

## Architecture

**1. Departments**

Departments are the `top-level organizational unit`. Every resource (tools, agents, pipelines, knowledge bases, etc.) belongs to a department, and users operate within the context of a department.

- A `default "General" department` is automatically created on first server startup.
- Only the `SuperAdmin` can create or delete departments.
- Each department maintains its own allowed roles and corresponding permissions.

**2. Roles**

Roles define the level of access a user has within a department.

| Role | Description |
|------|-------------|
| `SuperAdmin` | Platform-wide access. Not tied to any single department. Centralized control over all departments. |
| `Admin` | Highest authority within a department. Manages users, roles, permissions, groups, and resources within their own department. |
| `Developer` | Full CRUD and execute access on tools, agents, and pipelines within their department. |
| `User` | Read and execute access on agents and pipelines only (by default). |

!!! Note
    A member can have **only one role per department** but may have accounts in **multiple departments**.

**3. Role Hierarchy**

```
SuperAdmin (Level 3) ──── Platform-wide, all permissions
    │
    ├── Admin (Level 2) ──── Department-wide, manages users/roles/permissions
    │       │
    │       ├── Developer (Level 1) ──── Full CRUD + Execute on tools, agents, pipelines
    │       │
    │       └── User (Level 0) ──── Read + Execute agents/pipelines only
    │
    └── (Can manage any department)
```

---

## Authentication

**1. Registration**

-  Users register with `email`, `username`, and `password`.
-  After registration, users are in a `pending` state — they are not assigned to any department or role yet.
-  Users must contact a `SuperAdmin` or `department Admin` to get assigned a role in a department.
   - SuperAdmin can assign any role in any department.
   - Admin can only assign roles within their own department.
-  A dedicated `Contact Page` is available for registered users to reach out to admins.
   - A contact list of SuperAdmin and department Admin contacts is available to help users reach out.

**2. Login**

-  Users log in with `email`, `password`, and `department`.
-  Department selection is `required` for all users except SuperAdmin.
-  SuperAdmin can log in `with or without` specifying a department (department is optional for SuperAdmin).
-  Users must have `active status` to log in (both globally and within the department).

**3. SuperAdmin Bootstrap (First-Time Setup)**

When the platform is set up for the first time:

-  The `first registered person` becomes the `SuperAdmin`.
-  The default `"General"` department is created automatically with default roles:
   - `Admin` — Full permissions within department + Admin Tab
   - `Developer` — Full permissions within department
   - `User` — Agent read + execute only

**4. Password Management**

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
| `Remove Role from Department` | Admin (own dept) / SuperAdmin | Removes a role from a department. |
| `List Department Roles` | Admin (own dept) / SuperAdmin | View all roles configured for a department. |

### 4. User Management Within Departments

Admins have three categories of user management (accessible from the `Admin Tab`):

**User Assignment**:

- Assign roles to registered users within the department.
- SuperAdmin can assign any role in any department.
- Admin can only assign roles within their own department.


**User Update**:

- Update a user's role within the department.
- Reset/set temporary password for users.
- SuperAdmin can operate across all departments.

**User Access Management**:

- `Enable/disable` login access for users.
- Admin can disable users `within their own department only`.
- Users `cannot disable themselves`.
- Admin `cannot disable SuperAdmin` users.
- SuperAdmin can disable users `globally` (across all departments).

---

## Permissions

**1. Permission Matrix**

Each role within a department has a configurable permission matrix:

**CRUD & Execute Permissions (Resource-Level)**

Each of the following permissions can be toggled independently for `Tools` and `Agents`:

| Permission | Controls |
|------------|----------|
| `Read Access` | View tools/agents (and servers/pipelines) |
| `Add Access` | Create tools/agents |
| `Update Access` | Modify tools/agents |
| `Delete Access` | Delete tools/agents |
| `Execute Access` | Execute/run tools/agents |

!!! Important 
    Servers currently follow the **same permissions as tools**, and Pipelines currently follow the **same permissions as agents**. Separate permissions for Servers and Pipelines will be introduced in the next release.

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

**Independent Permissions**

These permissions are standalone and do not depend on other permissions:

| Permission | Description |
|------------|-------------|
| `Evaluation Access` | Access to evaluation features |
| `Vault Access` | Access to secrets/vault management |
| `Data Connector Access` | Access to data connector features |
| `Knowledge Base Access` | Access to knowledge base management |

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
```

**Validation Rule**: `Read Access` is a `prerequisite` — you cannot grant `Add`, `Update`, `Delete`, or `Execute` access for a resource type (Tools/Agents) unless `Read Access` is enabled for that same resource type.

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

**4 Managing Permissions**

| Operation | Who Can Do It | Restriction |
|-----------|---------------|-------------|
| `Set permissions`  | Admin (own dept) / SuperAdmin | Admin `cannot` modify Admin role permissions |
| `View permissions` | Admin (own dept) / SuperAdmin | Admin sees own dept only; SuperAdmin sees all |

!!! Important "Critical Rule"
    Only **SuperAdmin** can set or update permissions for the **Admin** role. Department Admins cannot modify their own role's permissions.

---

## Sharing Across Departments

Resources can be made accessible to other departments through two mechanisms:

**1. Public Access**

Marking a resource as `Public` makes it `read-accessible` to `all departments`.

- Available for: `Tools`, `MCP Servers`, `Agents`, `Knowledge Bases`, `Pipelines` (coming soon).

**2. Department-Specific Sharing**

Using the `Shared with Departments` setting, a resource can be shared with `specific departments` only.

- Available for: `Tools`, `MCP Servers`, `Agents`, `Knowledge Bases`, `Pipelines` (coming soon).
- `Public` and `Shared with Departments` are `mutually exclusive` — a public resource is already accessible to all, so specifying departments is redundant.

**3. Cascade Sharing**

When a higher-level resource is shared, its dependent resources are `automatically shared` as well:

**Agent Sharing Cascade**

```
Agent (shared/public)
  ├── Regular Tools ──── automatically shared/public
  ├── MCP Servers ──── automatically shared/public
  └── Knowledge Bases ──── automatically shared/public
```

**Pipeline Sharing Cascade (Coming Soon)**

```
Pipeline (shared/public)
  └── Agents
        ├── Regular Tools ──── automatically shared/public
        ├── MCP Servers ──── automatically shared/public
        └── Knowledge Bases ──── automatically shared/public
```

**4. Sharing Operations**

**Agent Sharing**

| Operation | Description |
|-----------|-------------|
| `Share Agent` | Share an agent with specific departments. This cascades sharing to the agent's tools, MCP servers, and knowledge bases. |
| `Unshare Agent` | Remove sharing of an agent from a specific department. |
| `View Sharing Info` | View the current sharing configuration for an agent. |
| `View Shared Agents` | View agents that have been shared with the current user's department. |

**Tool & MCP Server Sharing**

Sharing is managed via the `Public` and `Shared with Departments` settings during tool/server creation and update operations.

**Knowledge Base Sharing**

| Operation | Description |
|-----------|-------------|
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
| `Delete Access Key` | Delete an access key (creator only) |
| `View Tools Using Key` | View which tools are using a specific access key |
| `Update Own Access` | Update own allowed/excluded values for an access key |

`Key Rules:`

- Only the `creator` of an access key can delete it.
- Cannot delete an access key if tools are still using it.
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

The UI dynamically shows or hides `tabs and features` based on the logged-in user's permissions:

| UI Element | Required Permission |
|------------|-------------------|
| `Tools tab` | Read Access (Tools) |
| `Agents tab` | Read Access (Agents) |
| `Servers tab` | Read Access (Tools) — follows tools permission |
| `Pipelines tab` | Read Access (Agents) — follows agents permission |
| `Evaluation tab` | Evaluation Access |
| `Vault tab` | Vault Access |
| `Data Connectors tab` | Data Connector Access |
| `Knowledge Base tab` | Knowledge Base Access |
| `Resource Dashboard` | Add Access (Tools) or Update Access (Tools) |
| `Admin tab` | Admin or SuperAdmin role |
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

- First registered user becomes SuperAdmin.
- Has platform-wide access — all permission checks return `true`.
- Can log in without specifying a department.
- Can create/delete departments.
- Can assign any role in any department.
- Can disable users globally.
- Is the only role that can modify Admin role permissions.
- Cannot create or update groups (not tied to any department).

**Admin Rules**

- Highest authority within their own department.
- Can manage users, roles, and permissions in their department only.
- Cannot modify Admin role permissions — only SuperAdmin can.
- Cannot disable SuperAdmin users.
- Cannot disable themselves.

**Sharing Rules**

- `Public` and `Shared with Departments` are mutually exclusive.
- Sharing an agent cascades to its tools, MCP servers, and knowledge bases.
- Sharing a pipeline cascades to its agents and their resources (coming soon).
- Shared resources provide read-only access to target departments.

**Permission Rules**

- `Read` permission is a prerequisite for `Create`, `Update`, `Delete`, and `Execute` permissions.
- Chat toggle permissions (Execution Steps, Tool Verifier, etc.) require `Execute Agents` permission.
- Servers currently follow tool permissions; pipelines currently follow agent permissions. Separate permissions will be introduced in the next release.
- Resource Dashboard requires tool create/update permission.
- Vault operations require `Vault Access` permission.

**Tool/Agent Update Rules**

- Tools and MCP servers bound to an agent cannot be updated — must remove from agent first.
- Agents bound to a pipeline cannot be updated independently.

---
# RBAC & User-Level Access Control Documentation

## Table of Contents

1. [Overview](#1-overview)
2. [Current Implementation: Department-wise RBAC](#2-current-implementation-department-wise-rbac)
3. [Proposed: User-Level Access Control](#3-proposed-user-level-access-control)
4. [Implementation Plan](#4-implementation-plan)

---

## 1. Overview

### What We Have Now (Implemented ✅)

**Two-layer access control:**
```
Layer 1: Department Isolation → Users only see their department's resources
Layer 2: Role-Based Access   → Role defines what operations user can do
```

### What We Want to Add (Proposed 🔮)

**Third layer:**
```
Layer 3: User-Level Override → Grant/Deny specific resources to specific users
```

### Why User-Level Access?

**Current Problem:**
- All Developers in "Engineering" can access ALL Engineering tools/agents
- Cannot restrict Tool-A from User-X while allowing other Developers

**Solution:**
- Add user-level GRANT/DENY overrides on top of role permissions

---

## 2. Current Implementation: Department-wise RBAC

### 2.1 System Hierarchy

```
                        ┌─────────────────┐
                        │   SUPER_ADMIN   │
                        │  (System-wide)  │
                        └────────┬────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Department:   │    │   Department:   │    │   Department:   │
│       HR        │    │   Engineering   │    │     Finance     │
├─────────────────┤    ├─────────────────┤    ├─────────────────┤
│ ADMIN           │    │ ADMIN           │    │ ADMIN           │
│ DEVELOPER       │    │ DEVELOPER       │    │ DEVELOPER       │
│ USER            │    │ USER            │    │ USER            │
├─────────────────┤    ├─────────────────┤    ├─────────────────┤
│ 🔧 HR Tools     │    │ 🔧 Eng Tools    │    │ 🔧 Fin Tools    │
│ 🤖 HR Agents    │    │ 🤖 Eng Agents   │    │ 🤖 Fin Agents   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

**Key Points:**
- Resources (tools, agents) belong to a **department**
- Users belong to departments with a **role**
- Users can belong to **multiple departments** with different roles

### 2.2 Roles & Permissions

| Role | Tools | Agents | User Management |
|------|-------|--------|-----------------|
| **USER** | ❌ No access | ❌ No access | ❌ |
| **DEVELOPER** | ✅ CRUD + Execute | ✅ CRUD + Execute | ❌ |
| **ADMIN** | ✅ CRUD + Execute | ✅ CRUD + Execute | ✅ Own dept |
| **SUPER_ADMIN** | ✅ All depts | ✅ All depts | ✅ All |

### 2.3 Database Tables

```sql
-- Table 1: User credentials
login_credential
├── mail_id (PK)      -- User email
├── user_name
└── password (hashed)

-- Table 2: Departments
departments
├── department_name (PK)
├── admins[]          -- List of admin emails
└── created_by

-- Table 3: User-Department-Role mapping (KEY TABLE)
userdepartmentmapping
├── mail_id (FK)
├── department_name (FK)  -- NULL for SuperAdmin
├── role                  -- User/Developer/Admin/SuperAdmin
└── UNIQUE(mail_id, department_name)

-- Table 4: Role permissions per department
role_access
├── department_name (PK part)
├── role_name (PK part)
├── read_access: {"tools": bool, "agents": bool}
├── add_access: {"tools": bool, "agents": bool}
├── update_access: {"tools": bool, "agents": bool}
├── delete_access: {"tools": bool, "agents": bool}
├── execute_access: {"tools": bool, "agents": bool}
├── evaluation_access: bool
├── vault_access: bool
└── data_connector_access: bool
```

### 2.4 How Access Check Works

**File:** `src/auth/authorization_service.py`

```python
async def check_operation_permission(
    user_email: str,
    user_role: str,
    operation: str,      # 'create', 'read', 'update', 'delete', 'execute'
    resource_type: str,  # 'tools' or 'agents'
    department_name: str
) -> bool:
```

**Flow:**
```
┌─────────────────────────────────────────────────────────────┐
│                  CURRENT ACCESS CHECK FLOW                   │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│   Request: "Can user X do operation Y on resource Z?"        │
│                         │                                    │
│                         ▼                                    │
│              ┌─────────────────────┐                        │
│              │  Is SuperAdmin?     │                        │
│              └──────────┬──────────┘                        │
│                         │                                    │
│                Yes ─────┴───── No                           │
│                 │               │                            │
│                 ▼               ▼                            │
│            ┌────────┐   ┌─────────────────────┐             │
│            │ ALLOW  │   │ Same Department?    │             │
│            └────────┘   └──────────┬──────────┘             │
│                                    │                         │
│                           Yes ─────┴───── No                │
│                            │               │                 │
│                            ▼               ▼                 │
│                 ┌──────────────────┐  ┌────────┐            │
│                 │ Get role_access  │  │ DENY   │            │
│                 │ from database    │  │ (403)  │            │
│                 └────────┬─────────┘  └────────┘            │
│                          │                                   │
│                          ▼                                   │
│                 ┌──────────────────┐                        │
│                 │ Check permission │                        │
│                 │ for operation    │                        │
│                 └────────┬─────────┘                        │
│                          │                                   │
│                 Has Permission?                              │
│                    │         │                               │
│                   Yes        No                              │
│                    │         │                               │
│                    ▼         ▼                               │
│               ┌────────┐ ┌────────┐                         │
│               │ ALLOW  │ │ DENY   │                         │
│               └────────┘ └────────┘                         │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 2.5 Login Flow

```python
# Login requires department (except SuperAdmin)
POST /auth/login
{
    "email_id": "john@company.com",
    "password": "password123",
    "department_name": "Engineering"  # Required!
}

# Response includes department context
{
    "token": "eyJhbG...",
    "role": "Developer",
    "department_name": "Engineering"
}
```

### 2.6 Example: Resource Filtering

When a user requests tools/agents, they only see their department's resources:

```sql
-- Developer in Engineering calls GET /tools/get
SELECT * FROM tools_table 
WHERE department_name = 'Engineering'

-- They cannot see HR or Finance tools
```

---

## 3. Proposed: User-Level Access Control

### 3.1 The Gap

**Current limitation:**
```
┌─────────────────────────────────────────────────────────────┐
│  Department: Engineering                                     │
│                                                              │
│  Developers: Alice, Bob, Charlie                            │
│  Tools: Tool-A, Tool-B, Tool-C (Sensitive Payroll Tool)     │
│                                                              │
│  Problem: All 3 developers can access ALL 3 tools           │
│           Cannot restrict Tool-C from Bob                    │
└─────────────────────────────────────────────────────────────┘
```

**What we need:**
```
┌─────────────────────────────────────────────────────────────┐
│  Department: Engineering                                     │
│                                                              │
│  Alice  → Tool-A ✅, Tool-B ✅, Tool-C ✅                    │
│  Bob    → Tool-A ✅, Tool-B ✅, Tool-C ❌ (DENIED)           │
│  Charlie→ Tool-A ✅, Tool-B ✅, Tool-C ✅                    │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Proposed Solution: Three-Layer Access Control

```
┌─────────────────────────────────────────────────────────────┐
│                   ACCESS CONTROL LAYERS                      │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  LAYER 1: Department Isolation (EXISTING)                   │
│  ─────────────────────────────────────────                  │
│  • Users only see resources in their department             │
│  • Cannot access other department's resources               │
│                                                              │
│  LAYER 2: Role-Based Permissions (EXISTING)                 │
│  ──────────────────────────────────────────                 │
│  • Role defines what operations user can do                 │
│  • Same for ALL users with that role in dept                │
│                                                              │
│  LAYER 3: User-Level Overrides (NEW)                        │
│  ─────────────────────────────────────                      │
│  • GRANT: Give specific user access to specific resource    │
│  • DENY: Block specific user from specific resource         │
│  • Overrides role permission for that user                  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 3.3 New Database Table

```sql
-- New table: user_tool_access
user_tool_access
├── id (PK)
├── user_email           -- Which user
├── department_name           -- Which user
├── tool_id              -- Which tool
├── access_type          -- 'GRANT' or 'DENY'
├── granted_by           -- Admin who set this
├── granted_at           -- Timestamp
├── expires_at           -- Optional expiry
└── reason               -- Why this override exists
```

### 3.4 New Access Check Flow

```
┌─────────────────────────────────────────────────────────────┐
│              NEW ACCESS CHECK FLOW (Proposed)                │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│   Request: "Can user X access tool Y?"                       │
│                         │                                    │
│                         ▼                                    │
│              ┌─────────────────────┐                        │
│              │  Is SuperAdmin?     │                        │
│              └──────────┬──────────┘                        │
│                         │                                    │
│                Yes ─────┴───── No                           │
│                 │               │                            │
│                 ▼               ▼                            │
│            ┌────────┐   ┌─────────────────────┐             │
│            │ ALLOW  │   │ Same Department?    │             │
│            └────────┘   └──────────┬──────────┘             │
│                                    │                         │
│                           Yes ─────┴───── No                │
│                            │               │                 │
│                            ▼               ▼                 │
│    ┌───────────────────────────────┐  ┌────────┐           │
│    │ Check user_tool_access table  │  │ DENY   │           │
│    │ for this user + tool combo    │  └────────┘           │
│    └──────────────┬────────────────┘                        │
│                   │                                          │
│         ┌─────────┴─────────┐                               │
│         │                   │                                │
│   Found Override?     No Override                            │
│         │                   │                                │
│    ┌────┴────┐              ▼                               │
│    │         │    ┌──────────────────┐                      │
│  GRANT     DENY   │ Check role_access │ ← Existing logic    │
│    │         │    │ (fallback)        │                      │
│    ▼         ▼    └────────┬─────────┘                      │
│ ┌──────┐ ┌──────┐          │                                │
│ │ALLOW │ │DENY  │    Has Role Permission?                   │
│ └──────┘ └──────┘       │         │                         │
│                        Yes        No                         │
│                         │         │                          │
│                         ▼         ▼                          │
│                    ┌──────┐  ┌──────┐                       │
│                    │ALLOW │  │DENY  │                       │
│                    └──────┘  └──────┘                       │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 3.5 Decision Matrix

| Role Permission | User Override | Final Decision |
|-----------------|---------------|----------------|
| ✅ ALLOW | None | ✅ ALLOW |
| ✅ ALLOW | GRANT | ✅ ALLOW |
| ✅ ALLOW | **DENY** | ❌ **DENY** |
| ❌ DENY | None | ❌ DENY |
| ❌ DENY | **GRANT** | ✅ **ALLOW** |
| ❌ DENY | DENY | ❌ DENY |

**Key Insight:** User-level overrides take priority over role permissions.

### 3.6 API Endpoints (Proposed)

```
POST   /user-tool-access/grant    → Grant tool to user
POST   /user-tool-access/deny     → Deny tool from user  
DELETE /user-tool-access/revoke   → Remove override (revert to role)
GET    /user-tool-access/user/{email}  → Get user's overrides
GET    /user-tool-access/tool/{id}     → Get tool's overrides
```

### 3.7 Example Scenarios

**Scenario 1: Restrict sensitive tool**
```
Bob is a Developer (has tool access via role)
Admin denies Bob from "Payroll-Calculator" tool

Result: Bob can use all tools EXCEPT Payroll-Calculator
```

**Scenario 2: Grant special access**
```
Sarah is a User (no tool access via role)
Admin grants Sarah access to "Report-Generator" tool

Result: Sarah can ONLY use Report-Generator, nothing else
```

**Scenario 3: Temporary access**
```
Mike needs access to "Data-Migration" tool for 7 days
Admin grants Mike access with expires_at = 7 days from now

Result: Access auto-revokes after expiry
```

---

## 4. Implementation Plan

### 4.1 Files to Modify/Create

| File | Action | Purpose |
|------|--------|---------|
| `src/auth/models.py` | Modify | Add new Pydantic models |
| `src/database/repositories.py` | Modify | Add `UserToolAccessRepository` |
| `src/database/services.py` | Modify | Add `UserToolAccessService` |
| `src/api/user_tool_access_endpoints.py` | Create | New API endpoints |
| `src/auth/authorization_service.py` | Modify | Update access check logic |

### 4.2 Implementation Steps

```
Step 1: Add database table
        └── Create user_tool_access table in PostgreSQL

Step 2: Add Pydantic models  
        └── UserToolAccess, GrantRequest, DenyRequest, etc.

Step 3: Add Repository
        └── UserToolAccessRepository with CRUD methods

Step 4: Add Service
        └── UserToolAccessService with business logic

Step 5: Add API endpoints
        └── /user-tool-access/* routes

Step 6: Modify authorization_service.py
        └── Add user-level check before role check

Step 7: Test
        └── Verify GRANT/DENY overrides work correctly
```

### 4.3 Priority

| Priority | What | Why |
|----------|------|-----|
| 🔴 High | User-Tool Access | Most requested feature |
| 🔴 High | User-Agent Access | Already exists (commented), re-enable |
| 🟡 Medium | User-DataConnector Access | For sensitive DB connections |

---

## Summary

### What's Working Now
✅ Department isolation - users see only their dept resources  
✅ Role-based permissions - role defines operations allowed  
✅ Multi-department support - user can have different roles in different depts

### What We're Adding
🔮 User-level GRANT - give specific user access to specific tool  
🔮 User-level DENY - block specific user from specific tool  
🔮 Time-limited access - auto-expire overrides

### Access Check Priority
```
1. SuperAdmin? → ALLOW
2. User-Level DENY? → DENY (even if role allows)
3. User-Level GRANT? → ALLOW (even if role denies)
4. Role Permission? → Use role-based decision
5. Default → DENY
```

---


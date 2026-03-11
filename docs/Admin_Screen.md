# Admin Screen 
## Overview
The `Admin Screen` serves as the central hub for managing and monitoring key components of the system. 

- It is organized into multiple sections including `chat`, `Tools`, `Servers`, `Agents`, `Pipelines`, `Vault`, `Data Connectors`, `Knowledge Base`, `Resource Dashboard`, `Evaluation`, `Files` and an additional tab labeled `Admin`. 
- The `Admin` tab is specifically designed to provide administrators with advanced management capabilities.
- Within the `Admin` tab, you will find four main functional tabs that enable administrators to effectively manage users, oversee agent feedback, Installation, recycle bin management and Unused tools and agents, Groups and Role Control, Resource Management, and Inference Configuration.
---

## 1. User Management

The User Management section in the Admin tab allows administrators to manage user accounts, roles, and access within their department. Admins have three key capabilities:

- **User Assignment** — Assign roles to registered users within the department. SuperAdmin can assign any role in any department, while Admin can only assign roles within their own department.
- **User Update** — Update a user's role, or reset/set a temporary password for users within the department.
- **User Access Management** — Enable or disable login access for users. Admins can manage users within their own department, while SuperAdmin can manage users globally across all departments.

For detailed information on user management operations, permissions, and rules, refer to the RBAC documentation:

[:octicons-arrow-right-24: User Management Within Departments](RBAC.md#4-user-management-within-departments)


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
- **Permanent Deletion:** Permanently remove items that are no longer needed. This action cannot be undone.

> **Note:**
> Only users with administrative privileges can access the RecycleBin tab and perform restore or permanent delete actions.

## 5. Unused Tools, Agents and MCP Servers

The **Unused Tools, Agents and MCP Servers** tab displays all tools, agents and MCP Servers that have not been used or updated in the last 15 days. `Unused` means there has been no interaction with the agent or modification to the tool/agent during this period.

**Administrative Capabilities:**

- View a comprehensive list of unused tools, agents and MCP Servers.
- Delete unused tools, agents or MCP Servers directly from this tab.
- Deleted items are automatically moved to the RecycleBin for potential recovery or permanent deletion.

## 6. Control Tab

The **Control** tab in the Admin section enables administrators to manage groups and configure role-based permissions within their department.

**Group Management** — Organize users and agents into groups for collaborative access and shared vault secrets. Admins can create, update, and manage group memberships within their department.

**Role Permissions** — Configure role-based access control by defining what actions each role can perform on resources (Tools, Agents, Servers, Pipelines). Set Read, Add, Update, Delete, and Execute permissions at the role level.

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

---
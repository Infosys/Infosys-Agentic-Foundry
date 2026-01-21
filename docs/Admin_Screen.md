# Admin Screen 
## Overview
The `Admin Screen` serves as the central hub for managing and monitoring key components of the system. 

- It is organized into multiple sections including `Tools`, `Agents`, `Chat`, `Vault`, `Data Connectors`, `Files`, `Evaluation` and an additional tab labeled `Admin`. 
- The `Admin` tab is specifically designed to provide administrators with advanced management capabilities.
- Within the `Admin` tab, you will find four main functional areas that enable administrators to effectively manage users, oversee agent feedback, and evaluate system performance: `Register`, `Learning - Feedback Approval`, `RecycleBin` and `Unused Tools & Agents`.
---

## 1. Register

This tab is dedicated to user registration and role management. It enables administrators to create new user accounts by providing essential credentials and assigning appropriate roles.

**User Input Fields:**

- **Email:** Unique identifier for the user.
- **Password:** Secure password for login.
- **Role:** Dropdown selection among `Admin`, `Developer`, and `User`.

### User Roles and Permissions

The platform defines three distinct user roles `Admin`, `Developer`, and `User` each with specific access levels and capabilities.

**1. Admin Role**

Admins have full administrative privileges with unrestricted access to all system features. This role is typically responsible for platform-wide configuration and oversight.

**Admin Capabilities:**

- Onboard new tools and agents.
- Update existing tools and agents.
- Delete tools and agents.
- Upload files via the `Files` section.
- Interact with agents in the `Chat Inference` section.
- Manage the feedback learning, including review, approval, and learning updates.
- Perform model evaluations and view detailed performance metrics.

**2. Developer Role**

Developers are responsible for the setup, configuration, and maintenance of tools and agents. While they have extensive technical access, their permissions are slightly restricted compared to Admins.

**Developer Capabilities:**

- Onboard new tools and agents.
- Update tools and agents.
- Delete tools and agents.
- Upload files relevant to tool and agent functionality in the `Chat Inference` section.
- Interact with agents in the `Chat Inference` section.
- No access to feedback approval or evaluation metrics.

**3. User Role**

Users typically interact with tools and agents for practical use cases, testing, or demonstrations. Their permissions mirror those of Developers, focusing on hands-on interaction.

**User Capabilities:**

- End-user role with capabilities equivalent to the Developer.
- Can onboard, update, and delete tools and agents, upload files, and interact with agents.
- Typically engaged in the practical use and testing of tools rather than administrative oversight.

!!! Note
    Only the **creator (owner)** of a tool or agent has permission to **update** or **delete** it. This applies to all roles, ensuring secure and accountable resource management.

---

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
- Approve feedback to validate its effectiveness and relevance.
- Commit changes, which updates the agent's knowledge base or response logic accordingly.
- This process supports continuous learning and improvement of agents by integrating verified feedback.

---

## 3. RecycleBin

The **RecycleBin** tab lets administrators manage deleted tools, agents and MCP Servers. All removed items are listed here, providing a way to review them before permanent deletion.

**Key Features**

- **View Deleted Items:** See a list of all deleted tools, agents and MCP Servers.
- **Restore Functionality:** Restore mistakenly deleted items with a single click.
- **Permanent Deletion:** Permanently remove items that are no longer needed. This action cannot be undone.

> **Note:**
> Only users with administrative privileges can access the RecycleBin tab and perform restore or permanent delete actions.

## 4. Unused Tools, Agents and MCP Servers

The **Unused Tools, Agents and MCP Servers** tab displays all tools, agents and MCP Servers that have not been used or updated in the last 15 days. `Unused` means there has been no interaction with the agent or modification to the tool/agent during this period.

**Administrative Capabilities:**

- View a comprehensive list of unused tools, agents and MCP Servers.
- Delete unused tools, agents or MCP Servers directly from this tab.
- Deleted items are automatically moved to the RecycleBin for potential recovery or permanent deletion.

## 5. Installation

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
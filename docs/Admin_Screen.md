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

The **RecycleBin** tab lets administrators manage deleted tools and agents. All removed items are listed here, providing a way to review them before permanent deletion.

**Key Features**

- **View Deleted Items:** See a list of all deleted tools and agents.
- **Restore Functionality:** Restore mistakenly deleted items with a single click.
- **Permanent Deletion:** Permanently remove items that are no longer needed. This action cannot be undone.

> **Note:**
> Only users with administrative privileges can access the RecycleBin tab and perform restore or permanent delete actions.

## 4. Unused Tools & Agents

The **Unused Tools & Agents** tab displays all tools and agents that have not been used or updated in the last 15 days. `Unused` means there has been no interaction with the agent or modification to the tool/agent during this period.

**Administrative Capabilities:**

- View a comprehensive list of unused tools and agents.
- Delete unused tools or agents directly from this tab.
- Deleted items are automatically moved to the RecycleBin for potential recovery or permanent deletion.
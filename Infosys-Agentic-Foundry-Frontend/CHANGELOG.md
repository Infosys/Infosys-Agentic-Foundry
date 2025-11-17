# Changelog


## [1.5.3]
### Fixes
- Dataconnector defaut value modified. 
- File upload format corrected.

## [1.5.2]

- **RBAC implementation** : If loged in with USER as a role then we hide Tools, Agents, Vault and dataconnectors screens from menu and also hide the plan verifier toggle, tool verifier toggle, online evaluator and the execution steps in the chat screen.

## [1.5.1]
### Fixes
- Error popup now auto hides after showing error message.
- Text overflow sorted in tool execution.

## [1.5.0]

### Features and Fixes

**Consistency & Robustness**
- New screen added under Evaluation screen for user to run consistency and robustness on agents.
Export Agent
- Enhanced functionality with vulnerability fixes, updated configurations, and GitHub push support (requires environment variable configurations in UI).
- Added support for consistency and robustness checks for exported agents.
**Hybrid Agent**
- Added a new Hybrid Agent template, which is a pure Python-based template, with advanced capabilities present in other templates.
**Data Lifecycle Management**
- Implemented Time-To-Live (TTL) for automatic cleanup of unused tools/agents.
**Security**
- Fixed SQL injection vulnerabilities.
- Added malicious code detection and enhanced validation logic for tools.
- Implemented refresh token support for authentication, enhancing security and session management.
**Real-Time Updates**
- Added Server-Sent Events (SSE) for live streaming of evaluation results (LLM as Judge & Ground Truth).
**Model Integration**
- Connected bi-encoder and cross-encoder models to hosted servers via URLs.
- Added temperature slider for models in chat screen.
**Improvements**
- Revamped evaluation screen with three-column layout.
- Added support for tables, JSON, images, email and use-case specific cards in Canvas.
- Added error handler to control black screens.
- Removed .env file from codebase and replaced with .env-example.
- Evaluation screen modernized.
- Expanded MCP Server tooling with support for running/testing mcp tools.
- Introduced a new context flag that, when disabled, prevents old chat history from being included in the agent's context.
**Online Evaluation**
- Added support for running online evaluations during agent inference, enabling real-time assessment of agent outputs
**Defect Fixes**
- Fixed code preview plugin and Admin screen design issues.
- Removed guest user login.
- Fixed filter/tag issues in listing pages.
- Updated chat history to fetch respective sessionId.

## [1.4.2]

### Fix

- Removed monaco editor

## [1.4.1]

### Features

- Toggle feature for adding enabling or disabling of canvas.
- Toggle to include context for the chat.

### Fixes

- Admin screen scrolling fixed.
- Update user defect fixed.
- Added filter by server type in list of servers in tools and agents pages.
- Filter by tags to show only for Servers in Filter Modal in update agent.
- Guest login not able to chat.
- Application title in browser tab changed to 'IAF'.
- Tags button moved from the mapped section to the top of the screen in updated Agent page.
- Added page total count for list of tools, list of servers, list of servers.

## [1.4.0]

### Deployed on 15th Sep

### Features

- **Dynamic Canvas Previewer** - In chat screen based on user query we show custom canvas for more visualisation of the data, Canvas can render Table, Chart, Image, Programming code preview, JSON viewer dynamically based on the response.
- **MCP Servers** - Users can connect to MCP server(s).
- **Data Connectors** - Provision to connect private database. Currently supports SQLite and MySQL. MongoDB yet to be allowed.
- **Code Execution** - while tool onboarding users can run the python code to check for the output or errors.
- **Prompt/Query suggestions** - In chat screen now users can choose from history of prompts or from prompt suggestions.
- **JWT based Authentication** - Users are now authneticated using JWT bearer token.
- **Memory** - Imlemented memory implementation for system responses in chat for future context and system references.

### Fixes

- Code clean up.
- Minor corrections and improvsations on UI.
- Learning page added 'lesson'.

## [1.3.0]

### Changes - 30th July

- Chat UI Version 2.0
- New Page: Data Connectors
- API Endpoint Corrections due to Modularity
- Agent Screen Fixes: Meta/Planner Meta Agent, System Prompt, Agent Type
- ENV Variables for Configurations

## [1.2.0]

### Changes - 25th July

- New Pages: Ground Truth, Secrets
- Knowledge Base Integration for React Agent
- Defect Fixes: Recycle Bin, Tool Mapping, Admin Screens

## [1.1.0]

### Changes - 17th Jul

- File Upload Restriction by Type
- New Agent Templates: React-Critic Agent, Planner-Executor Agent
- New Pages: Update User, Recycle Bin
- Export Functionality

## [1.0.0] - Base Release

### Changes - 30th May

- Live Tracking Enabled
- Admin Screens: User Registration, Evaluation Metrics, Learning
- Tool Interrupt Support
- MKDocs Access via Help Button

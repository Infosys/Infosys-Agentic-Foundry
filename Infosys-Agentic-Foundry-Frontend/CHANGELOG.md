# Changelog

## [1.5.0]

### Features
- Refresh token implemented for logged in user.
- Execution of code made as common for tools and servers page.
- Chat screen:
  - Prompt library updates on every query submit.
  - Temperature slider for models.
  - Canvas ui improvised with table, json, image updates.
  - Canvas now supports Email and use-case specific card components.
- Evaluation screen:
  - Consistency robustness screen introduced.
  - UI revamped with three column layout.
  - Updated columns for efficiency screen.
  - Implemented live data update with server sent events in LLM as Judge and Ground truth screens.
- Admin screen:
  - Unused screen , added newly to list tools , agents, 
- Export agent functionality requires environmental variable configurations.
- Ground truth added auto reset when ever user modifies a form.
- Online evaluation added in chat screen for each system response.
- New agent template "Hybrid Agent" introduced..
- Improvised and made consistent look and feel for tools, server, agents listing pages.
- Error handler introduced to track the error and to reduce the blackscreen to users.
- File upload feature in tools onboarding.
- Vault screen ui updated.
- UI codebase ".env" file removed and replaced with ".env-example".
- LLM as judge made to appear based on role.

### Fixes
- Code preview plugin changed.
- Admin screen design issues sorted.
- Made  primary and secondary buttons to have similar looks and feel.
- Popups and overlays layer corrected.
- Removed Guest user login.
- 404 Error popup suppressed.
- Filter and tag related fixes done on list of tools, server, agents and onboarding/updating agent.
- Chat history modified to fetch respective sessionId to continue with respective conversation.
- Update agent screen on update tool. 


## [1.4.2]

### Fix

- removed monaco code editor

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

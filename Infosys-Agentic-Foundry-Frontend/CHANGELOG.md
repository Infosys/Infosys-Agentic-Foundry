# Changelog

## [1.8.0]

### Feature

New Modernised UI is designed with dark theme and light theme and consistent design across the pages.

- 13. Implemented GoogleAdk
- 14. File upload feature enhancement in chat page.
- 14. Tool to MCP server conversion changes.
- 15. Epoch and Threshold toggles enabled in admin screen.
- 15. Bug fixes:
    - In Add screens of tools, agents servers the default tag shows as No tags, show as General tag by default.
    - While updating the agent, the tool section is unable to open the tool details.
    - When a user logs in for the first time and tries to create a new agent, the system shows “Failed to load model".
    - In the Update Agent screen, the welcome message does not show an asterisk (*), while the agent goal and workflow description do show it.
    - In the agent welcome message, the popup or highlight behavior is inconsistent compared to other messages.
- 16. Parallelism of agent node in pipelines
- 17. Removal of pipelines get endpoint from the chat page.
- 18. On Add or Update of tools, servers, agents the form retains and shows the update screen untill user maually closes the FullModal. Also fixed the Api implementations , filtering in Server page instead of locally handling the data.
- 19. Added default_model_value to all the model dropdowns.
- 20. File upload removed from Tool Add and Server add instead reads from UI itself in the Code Snippet.
- 21. Bug Fixes
   1. remove the file context and message queue toggle for google adk and pure python framework types.
   2. agent type filter changes in evaluation metrics.
   3. Remove the feedback buttons for the pipeline agents in final response and old chats responses.
   4. Export agent modal configuration changes.
   5. Change "Generate" label "Convert to MCP"
   6. Realtime Filtering is happening on created by - All/Me, Filtering should only happen after the user clicks on "Apply"
   7. Search button should be placed beside search bar to be able to click by the "Mouse"
   8. In chat page on clicking "X" in select tools pop up in tool verifier toggle settings, it's not working.
- 22. Bug Fixes
   1. add specific icons for specific databases
   2. Text is overlapping with the copy and expand icons in tools/server/agents pages.
- 23. Sast scan issues fix. Microphone changes in chat page.
- 24. Agent Form page issues fix.
- 25.  - 26.  Bug Fixes
  - 1. data connectors logo colors should not change while switiching between the light and dark theme.
  - 2. In Add Resources, filter option is not working.
  - 3. Add a clickable search icon next to the search bar in the ‘Add Resources’ section of Agents.
  - 4. The ‘General’ tag remains selected even when the user chooses other tags. Since ‘General’ is selected by default, it should be automatically removed if the user deselects it or selects alternative tags.
- 27. 
 - 1. vault page group value rendering issue fix.
 - 2. Version number visibility issue.
 - 3. tag selector rendering issue in tool/agents/servers pages.
 - 4. welcome message format changes in chat page.
 - 5. Chat-bot icon overlapping issue in tool onboarding page.
 - 6. Knowledge base update endpoint integration.
 - 7. Agent onboarding payload changes.
 - 8. Theme issues for the input fields.
 - 9. update agent page tool and servers rendering issue fix.
 - 10. In list of tools page duplicate data rendering issue.
 - 28. 
 - 11. Removal new card  creation from all the pages.
 - 12. Theme button postion changes.
 - 13. when the menu is expanded/collapsed the cards width is changing issue fix.
 - 14. Submenu is hiding when the loader is present in admin pages, always enable the menu.
 - 15. In login, register, contact pages have for theme preferences.
 - 16. In contact page, on click of the copy button text is not shown in dark theme.
 - 17. On agent update, don't enable toggles to true like "regenerate welcome message", "regenerate system prompt", "regenerate file context prompt".
 - 29. filtering issues fix in tools/agents/servers.
 - 30. Chat page enhancement changes.
 - 31. 
  - 1. when updating agent, let's say agent having some resources already, when you click on "+" resource button and clear all selection and without save selection if you click on cross mark, then already existing resources for that agent not displaying. 
  - 2. Frequent logout issue fix.
  - 3. When admin changes password, so when you login using temporary password, it will redirect to a card to change password. So, when you type incorrect current password and trying to change password, it is again redirecting to login page.
  - 4. when switching between tabs, search term is not cleared in valut page.
  - 5. LLM As judge, same model value shown in two dropdowns.
  - 6. On ground truth page, when select model name, agent type, agent name, upload a file and LLM grade toggle to true and click on execute button, disable to edit on that page as execution going on at that time.
  - 7. In metrics/Evaluation records, when you select any filter called "React", then from backend we are getting "No evaluation data found", but still Ui is showing some records.
  - 8. Agent type not showing in list of agents in learning page for admin menu.
- 32. Include validator toggle for hybrid agents. For knowledge bases in update agent page to render update the endpoint.
- 33. Enhancement changes.
- 34. Bug fixes
- 1. In data connectors page for the editor styling changes.
- 2. On click of the coding agent button, trigger the endpoint to fetch the pipeline id data instead of the static value from the UI to send to payload while inferencing.
- 3. In LLM as judge page while execution is in progress do not allow for input changes.
- 4. Hide the code execution button and access control guide in recycle bin for servers.
- 5. In value page for all the tabs enable the secret value to edit.
- 6. In framework for all the pages use the font style as normal for consistency by replacing from italic.
- 7. In recycle bin for agents, tools, servers do not show the copy and expand buttons.
- 8. In ground truth page disable the fields while execution is in progress.
- 9. In data connectors, in query modal when the results are not present still showing the empty container in ui , do not render the empty container. render only when data is present.
- 10. In register form page, on hover the href link content is not visible.
- 11. In consistency add form page, the fields data updation is depend on model name filling remove that logic. User can fill the form in any order.
- 12. on click of regenerate button in the final response block show the regenerating loading text until the response is rendered.
- 13. Code editor cursor positions issues fix.
- 14. for add server endpoint payload issues fix.
- 35. Bug fixes
- 1. In evaluation records, tools efficiency, agents efficiency pages, When you apply any filter that returns no evaluation data, and then when you clear selection and apply, no data is showing.
- 2. The selected agents in filter dropdown,show on top as selected.
- 36. Disable the convert to mcp button when the validators are selected.
## [1.7.0]

- 1. As part of SAST fixes "password" is modified to "user_pwd" in DataConnectors Screen.
- 2. Include plan verifier toggle for meta planner agent.
- 2. For meta and planner meta agents, when agent verifier is on, the label has to show as Agent calls and for other agent types it has to be Tool calls.
- 2. For meta and planner meta agents, show the feedback buttons for the final response.
- 2. In groundtruth page for the error streaming response no toast message is rendering and screen is in idle state without any information.
- 3. While updating the meta agent and the meta planner agent in the Add section, for the list of agents include the react critic agents and planner executor agents.
- 3. While onboarding the meta agent and the meta planner agent in the list of agents include the react critic agents and planner executor agents.
- 4. Include Validator toggle for meta and planner meta agents.
- 4. For the success and error toast messages rendering on the screen, the key (status_message) from the backend is changed to message.
- 5. Added `start_timestamp` display for all user queries. Handles null timestamps gracefully when not provided by the backend.
- 6. For planner agents, displaying plan in plan irrespective of plan verifier toggle on or off
- 6. Added validation for username during user registering
- 7. after slecting all the dropdowns in chat page need to hit endpoint based on ressponse when we enable tool verifier need to show popup and display list based on selected value and need to send the selected value in the payload
- 8. I have selected agent type ,modal and agent and enabled tool verifer on and again i changed agent type tool verifier is defaultly enabled is fixed.
- 9. Sequence of agent changes with four nodes.
- 10. Include Validator toggle for hybrid agent.
- 11. For admin role, Enable the installation of modules.
- 12. Recycle bin and TTL for servers.
  13. Removed Validator toggle for hybrid agent.
- 12. Removed the pipeline agent type from the list in agent onboard, consistency tab, groundtruth .

## [1.6.0]

### Feature

- Introduced Validators:
  User can create a validator just like a tool and map it to an agent while onboarding or updating. So while using that agent in the chat screen the agent responses will be validated internally. If user wants to see the validations happening they have to enable the validator toggle in the chat screen.
- Introduced Context Agent (@) in the chat screen:
  We have introduced a new button "@" with which user can add a context agent along with the main agent there by we can train the context agent on the main agents's queries and responses.
- Introduced Live Steps using data streaming (SSE):
  Live steps are now displayed when ever user sends a query, which will display step by step as the agent progress and user can click and see the details of the steps like an accordion.
- Introduced Agent Verifier toggle for Meta and Meta Planner templates in chat screen just like tool verifier for other agent templates.
- Introduced a Button in header to trigger Grafana dashboard in new tab.
  File upload section UI modified. Introduced multiple files upload.

### Fixes

- Plan and Feedback to be displayed accordingly based on the active toggles and respective agent flow with and without context agents.
- Data connectors while running query the payload is now encoded and key is changed to 'data'.
- Data connectors CRUD operation for mongoDB while insert only one mode is applicable.
- Delete agent custom modal popup added.
- Security fixes
- Canvas not to show for older queries.
- Refresh token implemented for streaming api.
- For user login showing only chat,files and groundtruth.

## [1.5.3]

### Fixes

- Data connector port set to 0. File upload corrections for knowldge base and normal files.

## [1.5.2]

- If the logged in user role is USER then we have to hide Tools, Agents, Vault screens from menu and they should not be able to navigate to those pages even if they enter the url.Also if the logged in user role is USER then we have to hide the plan verifier toggle, tool verifier toggle and the execution steps button in the chat screen.
- When login as user hide dataconnectors and online evaluator in verifier settings in chat page

## [1.5.1]

- Error popup not auto hiding.
  Test overflow in tool executor to wrap with in the container.

## [1.5.0]

### Features and Fixes

- For the table component, download button css changes.
- For the json component, to render the content inside the data object.
- In the admin page, update user tab when user provides inputs for email and password fields, in payload email, new_password, role also sent as select role which is the default value but it should not send the role in the payload.
- Admin screen ui updated , scroll issues fixed. Removed monaco editor.
- In the groundtruth page reset the execution results when the inputs are changed and removal of multiple scrolls.
- Defect fixes :
  - Made all screens Close button to Cancel button.
  - Select agent if default disable model and agent dropdowns.
  - Star icon should be refresh if the list is empty
  - Update agent proper error message is not shown
  - Knowledge base ui overlay fixed
  - Admin screen register and update user fixed
    Ui improvisations done for tools and server pages
    added tool tip for agent names on cards
    Application title in browser tab changed from React App to "IAF"

- Merged Interim fixes (1.4.1) to Dev. fixed chat scree payload issue, fixed filter popup to work similar across the screens
- Added upload file field while creating the tool similar to servers.
- Removed monaco editor as it is throwing error and replaced with plain text area
- Added error handler to handle errors in application, code, api response. Added response time for api calls to console log.
- Replaced monaco editor with react-ace for displaying and highlighting code
- Added one more server type as Remote and added one more field for remote server type as Headers.
- Export agent changes with .env configurations,Upload file is still showing even after logging out defect fix changes. Added Online evaluation tool flag for thumbs up , thumbs down of tool and plan verifiers.
- Plan feedback changes in the execution steps.
- Temperature slider changes in chat page. Code editor cursor fix. Error handler corrections and fallback.
- Refresh token implemented to retain user session, Code editor height fixes, added iafButton common css, list of tools, agnets, servers - search and filter page alignment modifications. response time added for every bot chat, timeformatter util to format date and time, caht option disabling removed, fileupload error popup moved to addMessage popup, removed add server button adding / updating text, corrected addserver modaloverlay and modal overlap, parallel user auto logout, chat options disabling removed, prompt suggestion updates on every query submit
- Hybrid agent template changes in agent on board page, update agent page, chat page, temperature slider changes in chat page.
- Fixed Server page overlay issue, resize issue and codeeditor wrongly added for Agent Tool description
- Executor Panel component created for executing tools and server code. Fixed on click of loader , in tools and servers the loader got closed.
  404 error popup supressed for now.
- canvas changes for email type. Logout on 401 issue fixed. Added EXTERNAL tags on filters.
- Valut screen icon modifications, Code editor improvised, Run tool updated with component, modified run tool response structure for server. Remove ".env" file and replaced with .env-example,Export agent changes for the github configurations.
- In chatpage when click on chat history and selected one value from the list and when i change modal that chat history sessionId is using current sessionid instead of old sessionID.
- For the hybrid agent, enable the servers tab while onboarding and updating the agent.
- For the tags filter, in the agent onboarding, and update agent when switching between the tab, the filters state has to reset.
- LLM as Judge changes for the developer role, in the Agents Efficiency include one more column as to be included as communication_efficiency_score.
- For the hybrid agent Online Evaluator toggle has to be enabled.
- When user apply both a filter and a search together, the filtering works correctly. However, when user change the filter without modifying the search value, the backend processes the new filter and returns a response, but the updated results are not displayed in the UI. But, if user open the filter panel again and click 'Apply Filter' without making any changes, the results are shown correctly.
- As a guest when user opens the 'Update Tool' popup and click on 'Update', the login popup appears behind the update popup.
- As a guest ,when user tries to update a server using the 'Update Server' popup, the login popup does not appear.
- During tool onboarding, once a file is uploaded via the 'Upload File' option, the code snippet editor should be disabled to prevent manual editing.
- added a new tab in admin screen as unused where we get unsed agents list and tools list where user can delete the unsed agents and tools.
- removed multiple endpoints in servers (getAllServers endpoint is triggering multiple times)
- For the hybrid agent, enable the like and dislike buttons for the old responses.
- In update server page, disable the server type and header dropdowns. For the TTL updated the threshlod value.
- On the Servers page, after applying filters and performing a search, the results are correctly filtered. However, when user clicks the refresh button, all selected filters are cleared visually, but the server list does not reset. It still shows only the servers from the previously applied filters instead of displaying all servers.
- In the update agent, while trying to update the tool added the missing request body parameters.
- After uploading a file in onboarding server and if we click on run code option it should throw a error as enter valid code but instead it opening the run code pop up in blank
- Evaluation page ui revamp.
- Not showing any error response when unsupported file type is uploaded in upload file option for tools/servers.Error responses are coming out of the error pop up box.
- Removed "Login as Guest" button from login screen
- In the export agent modal modified the fields conditions as optional or required.
- when all the toggles are disabled, if we ask a query we are getting response in text format.But If we click regenerate option we are getting response in Canvas format (For all agent types except meta and meta planner).
- planner dislike input issue is resolved for all agent types.
- SSE for LLM as Judge page, Groundtruth page.
- Canvas changes for the card component with type json for Sunrise useCase.
- Vulnerability changes on add server, consistency, ground truth screens, tool efficiency made to look similar to agent efficieny in evaluation screen.
- Updated the stylings for the canvas card component.
- Canvas component for type text to render for multiple components if present.
- While onboarding the agent the modal value issue.
- If multiple tags are selected in server type and click on apply filter, only one filter is getting applied in the payload.
- Changed Export and Deploy text to Export and push to Github text.
- Image preview in Canvas screen is enabled

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

# Changelog
## [1.2.1]
### Changes
 - Added a new page as secrets.
 - Integrated all endpoints for create,update,delete and copy
 
## [1.2.0]
### Changes
- In agent on board page, disabling of the form without the selection of tools/agents.
- In agent update page, unmapped tools and mapped tools api defects are fixed.
- In admin screen update user page changes for password and role keys .
- In admin screen recycle page agnets and tools edit defects are fixed.
- Update agent page changes for the system prompt and tool id fields changes as per the type change from BE.
- Export button styling changes in the list of agents page.
- In tool on boarding page, for the description field styling changes.
- Ground Truth page implemented.

## [1.1.1]
### changes
- In the list of agents page in the agent type dropdown,include two agent type values : React Critic Agent, Planner Executor Agent.
- In Agent on board page, agent type dropdown,include two agent type values : React Critic Agent, Planner Executor Agent.
- On selection of this agent types render tools list.
- Accordingly invoke the endpoint for the onboarding agent.
- In the Update agent page display the system prompt dropdowm values as well accordingly based on the selection of the dropdown value render the system prompt value.
- Accordingly invoke the endpoint for the update agent.
- In the chat page for both the templates display the tool verifier toggle.
- for the planner executor agent display the plan varifier as well.
- Accordingly the existing logic for the feedback and approval as to be applied to this new templates as well.
- Added Update User and Recycle-Bin for admin screen.
- In Update User page a user can change the password and role.
- In Recycle-Bin page deleted agents and tools list are shown and there we can restore or delete.

## [1.1.0]
### Changes
- In agent on board page enabling of the form without the selection of tools/agents and removed the scroll bar for the container.
- On deleting or updating the agent refresh the page to get the updated list.
- Export functionality for the agents(single and multi agents)

## [1.0.1]
### Changes
- Login validations improvised.
- In agent on board page align the fields with stylings.
- For the agent goal and workflow description in agent on board page include the button to expand the text and remove the initial onclick event handler for expansion.
- Included .msg, .db, .json, .img, .jpg, .png, .jpeg extensions in the file upload 


## [1.0.0] - Base Release
### Added
- Live tracking included
- Admin page with register
- Admin page with Metrics
- Admin page with learning
- Introducing version number on top right corner
- Disable send button for empty or just space in chat
- Agent type indicators in agent list
- Added planner meta agent
- Tool interrupt
- Help button navigation to mk docs
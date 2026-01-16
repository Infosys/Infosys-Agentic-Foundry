# Canvas Screen in Chat Inference

The Canvas Screen is an advanced visualization feature in chat inference, automatically triggered based on the user query and the agent's response type. It provides a dynamic and interactive way to present structured data, images, and graphical outputs within the chat interface.

## Canvas Screen Display

When a user submits a query that results in structured, visual, image-based, or email-related data, the Canvas Screen can be viewed by clicking on the "View Details" option.

!!! Example
	- After selecting the agent type, model, and agent, if the user queries "list all the available products," the Canvas Screen will appear in a tabular format when "View Details" is selected.
	- If the user requests to "send an email summary," the Canvas Screen will display the email content in a dedicated email component.

## Supported Output Formats

- **Tabular Format:**
	- Displays data in a table for easy viewing and comparison.
	- Example: Listing products, users, or any structured dataset.

- **Graphical Representations:**
	- Supports charts and graphs for visualizing trends, analytics, or relationships in the data.
	- Example: Displaying sales trends, performance metrics, or statistical summaries.

- **Image Display:**
	- If the agent is capable of image generation or retrieval, the Canvas Screen can display images relevant to the user query.
	- Example: Showing generated images, product photos, or visual search results.

- **Email Component:**
	- Renders email content in a dedicated, formatted card for easy reading and interaction.
	- Example: Displaying generated email summaries, notifications, or correspondence.

- **Use-case Specific Card Components:**
	- Presents information using custom card layouts tailored to specific use cases.
	- Example: Showing order details, user profiles, or task summaries in visually distinct cards.

## Usage Highlights

- The Canvas Screen enhances the user experience by providing rich, context-aware visualizations directly in the chat workflow.
- It is especially useful for agents that return complex data, visual analytics, or image-based results.
- The format (table, graph, image) is chosen automatically based on the agent's response and the nature of the query.

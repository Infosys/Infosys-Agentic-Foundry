Dynamic Canvas Feature: Developer Instruction
This project implements an AI agent system with three core UI areas:

Tools Page: For creating and managing agent tools.

Agent Page: For integrating tools and managing agents.

Chat Screen: For using agents to automate user tasks with AI, all via REST APIs.

Tech Stack:
Frontend: React 19 (no SSE or websockets, REST only).
Backend: Python with LangChain (separate project).

🎯 Canvas Feature Requirements
When the user interacts with the chat agent and the backend returns data (e.g., programming code, files, text, charts, weather, dashboard data, PDFs, Excel, dataflow diagrams, etc.), a dynamic Canvas should slide in from the right, displaying the appropriate component and content based on the response.

Canvas Behavior
Canvas slides in smoothly from the right with animations.

Canvas appears inside .messagesWrapper. When open:

.messagesContainer shrinks to 30% width of askAssistantContainer.

Canvas occupies remaining 70%.

Hidden by default. Can be manually opened/closed, or toggled via a “deticative” button on chat bubbles.

If a new component is required (e.g., user prompts for new code), refresh the canvas with new content.

Each canvas instance is context-aware—clicking the button on a past chat bubble renders that historic content.

Resembles “Google Gemini Canvas” or “Claude Artifact”.

Modular & Dynamic Rendering
All Canvas-related components should reside under:
components/Canvas/

Use a widget/component mapping pattern:

js
// Example widget map for dynamic rendering
const widgetMap = {
  form: FormComponent,
  table: TableComponent,
  card: CardComponent,
  code: CodeViewerComponent,    // and so on
  // ...add more as needed
};

function DynamicWidget({ type, props }) {
  const Widget = widgetMap[type];
  return Widget ? <Widget {...props} /> : null;
}

The api responses MUST use the parts format structure:
"parts": {
  "components": [
    {
      "type": "text|chart|table|image",
      "data": {
        "content": "...", // for text
        "headers": [...], "rows": [[...]] // for table
        "data": [...] // for chart
        "url": "..." // for image
      },
      "metadata": {
        "title": "...",
        "description": "..."
      }
    }
  ]
}

The Canvas rendering system ONLY supports the parts format. Legacy formats (executor_messages, final_response, etc.) are no longer supported for Canvas rendering.

Parts Format Requirements:
- text: Text content with markdown support
- chart: Chart/graph data with automatic visualization
- table: Structured data with headers and rows
- image: Image URLs or base64 encoded images

The PartsRenderer component handles the parts format and renders each component using the appropriate widget. Any response without the parts format will not trigger Canvas rendering.

Render code responses using a styled, highlighted code viewer with a copy option. Plan for future code preview/execute features.

Canvas should be responsive. It should have the feature to slide to adjust width maximum 75% of screen width, minimum 30% of screen width.
Design is minimalistic, sleek, modular, and syncs with existing styles in:

AskAssistant.module.css

ChatBubble.module.css

ChatInput.module.css

ToolCallFinalresponse.module.css

Any SVGs/icons used in the Canvas should match the styling and convention used in AskAssistant.jsx, especially for action buttons.

Additional Guidelines
Use only well-maintained, React 19-compatible libraries; reuse existing plugins when possible—keep new dependencies minimal.

Handle errors, fallbacks, and loading gracefully with subtle animations, loaders, and error placeholders.

Code should be modular, reusable, and well-structured.

Ensure all features and additions are future-proof and do not introduce breaking changes.

Summary:
The Canvas acts as a dynamic content wrapper, intelligently rendering the right component(s) based on agent API response. It integrates tightly with chat UI and provides an intuitive user experience for complex data types, similar to Google Gemini Canvas or Claude Artifact, while adhering to our minimal design principles and React 19 best practices.
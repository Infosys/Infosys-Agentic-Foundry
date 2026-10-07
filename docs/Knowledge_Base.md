
# Knowledge Base Integration

A knowledge base is a structured repository of information that agents can use to enhance their reasoning, provide more accurate answers, and support advanced use cases. Integrating knowledge bases into Agentic Foundry allows agents to access domain-specific data, documents, or FAQs during inference.

A knowledge base serves as an external memory for agents, enabling them to:

- Retrieve factual information and context.
- Provide consistent, reliable, and context-aware answers to user queries.
- Support advanced reasoning, document search, and question answering workflows.

---

## Creating a Knowledge Base

Knowledge bases are created and managed from the **Tool Page**. This interface allows you to upload documents (PDF, TXT), enter a name for the new knowledge base, and add it to the centralized directory.

**Supported File Types**

| Category | Formats |
|----------|---------|
| Documents | PDF (`.pdf`), Text (`.txt`), Word (`.docx`) |
| Spreadsheets | Excel (`.xlsx`), CSV (`.csv`) |
| Presentations | PowerPoint (`.pptx`) |
| Images | PNG (`.png`), JPEG (`.jpg`, `.jpeg`), GIF (`.gif`) |

!!! note "File Upload Limits"
    Excel and CSV uploads are subject to configurable row limits. Large-file processing uses extended timeout settings to handle high-volume data.

!!! warning "Removed Formats"
    The legacy Word format (`.doc`) is no longer supported. Use `.docx` instead.

**Duplicate File Handling**

If a file with the same name already exists in the knowledge base, the platform displays a conflict prompt allowing you to choose whether to overwrite or skip the upload. Duplicate uploads are routed to the authenticated user's folder.

**Default LLM Model**

Knowledge base queries are answered using the platform's configured default LLM model. This ensures consistent inference behaviour without requiring per-knowledge-base model configuration.

## Adding Knowledge Bases to Agents

Once knowledge bases are created, they can be added to agents during the agent onboarding process. This allows agents to access domain-specific information and provide more accurate, context-aware responses.

**How to Add Knowledge Bases:**

1. Navigate to the `Agent Onboarding` page
2. Go to the `Resources` tab
3. In the `Knowledge Bases` section, select one or more knowledge bases that you want the agent to use
4. The selected knowledge bases will be available to the agent during inference

**Benefits:**

- `Persistent Configuration` — Knowledge bases are configured at the agent level, so they're always available when the agent is used
- `Multiple Knowledge Bases` — Add multiple knowledge bases to support different domains or topics within a single agent
- `Context-Aware Responses` — Agents leverage the selected knowledge bases to provide accurate, domain-specific answers
- `Flexible Management` — Update or modify knowledge base assignments as your information needs change

This approach ensures that agents have consistent access to relevant information sources, making them more reliable and effective for specialized tasks.

---

## Execution Steps: How the Agent Uses Knowledge Bases

When a query is submitted, the agent analyzes the question and determines which of the selected knowledge bases are most relevant. The agent then retrieves information from the appropriate knowledge base(s) to construct its response.

The execution steps can be viewed to see exactly how the agent is referencing the correct knowledge base for the query. This transparency helps users understand the reasoning process and verify that the agent is using the intended sources.

For example, if a technical question about a product is asked, the agent will reference the product documentation knowledge base. If the query is about company policy, the HR or policy knowledge base will be used, provided both are selected.
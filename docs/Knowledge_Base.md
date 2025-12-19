
# Knowledge Base Integration

A knowledge base is a structured repository of information that agents can use to enhance their reasoning, provide more accurate answers, and support advanced use cases. Integrating knowledge bases into Agentic Foundry allows agents to access domain-specific data, documents, or FAQs during inference.

A knowledge base serves as an external memory for agents, enabling them to:

- Retrieve factual information and context.
- Provide consistent, reliable, and context-aware answers to user queries.
- Support advanced reasoning, document search, and question answering workflows.

---

## Creating a Knowledge Base

Knowledge bases are created and managed from the **Tool Page**. This interface allows you to upload documents (PDF, TXT), enter a name for the new knowledge base, and add it to the centralized directory.

---

## Using Knowledge Bases in Inference

During chat inference, one or multiple knowledge bases can be selected for the agent to reference while answering queries. This is done using a dedicated icon in the chat interface, allowing the agent's knowledge to be tailored to the context of the question.

Selecting the appropriate knowledge base(s) ensures the agent provides contextually accurate and precise answers, which is especially useful for organizations with multiple knowledge bases serving different departments or domains.

---

## Execution Steps: How the Agent Uses Knowledge Bases

When a query is submitted, the agent analyzes the question and determines which of the selected knowledge bases are most relevant. The agent then retrieves information from the appropriate knowledge base(s) to construct its response.

The execution steps can be viewed to see exactly how the agent is referencing the correct knowledge base for the query. This transparency helps users understand the reasoning process and verify that the agent is using the intended sources.

For example, if a technical question about a product is asked, the agent will reference the product documentation knowledge base. If the query is about company policy, the HR or policy knowledge base will be used, provided both are selected.
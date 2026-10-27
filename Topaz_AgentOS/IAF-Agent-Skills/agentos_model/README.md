# agentos-model

AgentOS model-provider metadata and LLM registry components.

This package owns the composable model layer:

- `ModelRegistry`
- `ModelProviderAdapter`
- provider-neutral reasoning capability metadata
- Azure Responses, Vertex/Gemini, and Anthropic chat adapters

Historical `iaf_agent_skills.model_*` and provider chat adapter imports remain
compatibility shims.

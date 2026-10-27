# agentos-engine

Composable AgentOS engine facade for skill routing, execution modes, memory, and
session state.

This package intentionally starts as a compatibility facade over the historical
`iaf_agent_skills` package. It gives adopters the target `agentos_engine` import
surface while preserving existing full-product behavior. Internal modules can be
moved behind this facade incrementally without breaking callers.

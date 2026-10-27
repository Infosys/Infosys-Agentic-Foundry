# Partner Adapter Starters

These examples show the shape expected by the runtime provider factory. Use
them as starting points for integrations with another product team's registry,
tool catalog, or policy engine.

Example env values:

```bash
SKILL_PROVIDER=partner_adapters.memory_skill_provider:MemorySkillProvider
TOOL_PROVIDER=partner_adapters.sample_tool_provider:SampleToolProvider
HOOK_PROVIDER=partner_adapters.sample_hook_provider:SampleHookProvider
```

Leave any slot at `default` to keep the built-in AgentPro implementation.

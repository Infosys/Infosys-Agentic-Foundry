# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from typing import Dict, Any, Callable, AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.utils.context_utils import Aclosing


class RouterAgent(BaseAgent):
    route_sub_agent_decision_function: Callable[[Dict[str, Any]], str]
    """
    route_sub_agent_decision_function (Callable[[Dict[str, Any]], str]):
        Decision callback that receives the agent's complete state dictionary and should return
        the name of a sub-agent to execute.

        Args:
            state (Dict[str, Any]): State dictionary of the agent.

        Returns:
            str: Exact name of one of the available sub-agents to run. If the returned name
            does not match any sub-agent (or an empty string is returned), no sub-agent is
            executed.
    """

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        if not self.sub_agents:
            return

        agent_to_run: str = self.route_sub_agent_decision_function(ctx.session.state)
        for sub_agent in self.sub_agents:
            if sub_agent.name == agent_to_run:
                async with Aclosing(sub_agent.run_async(ctx)) as agen:
                    async for event in agen:
                        yield event
                return



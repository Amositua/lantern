"""Root ADK agent for the orchestrator — will grow sub-agents for
perception, clarifying, execution, and safety review as those come
online."""
from google.adk.agents import Agent

from common.config import get_settings

settings = get_settings()

root_agent = Agent(
    name="lantern_orchestrator",
    model=settings.gemini_pro_model,
    description="Routes a user's turn to the right Lantern agent and sequences the result.",
    instruction=(
        "You coordinate Lantern's specialist agents. You never take a high-stakes "
        "action yourself; you route to the agent responsible and wait for its result."
    ),
)

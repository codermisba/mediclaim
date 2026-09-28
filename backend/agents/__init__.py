"""The five MediClaim agents, in pipeline order.

    input -> document understanding -> extraction -> validation -> generation -> review

Each module exposes ``AGENT_NAME``, a ``SYSTEM_INSTRUCTION``, an input/output
Pydantic model pair and an ``async def run(...)`` function.
"""

from agents import (  # noqa: F401
    document_agent,
    extraction_agent,
    generation_agent,
    input_agent,
    review_agent,
    validation_agent,
)

AGENT_ORDER = [
    input_agent.AGENT_NAME,
    document_agent.AGENT_NAME,
    extraction_agent.AGENT_NAME,
    validation_agent.AGENT_NAME,
    generation_agent.AGENT_NAME,
    review_agent.AGENT_NAME,
]

__all__ = [
    "input_agent",
    "document_agent",
    "extraction_agent",
    "validation_agent",
    "generation_agent",
    "review_agent",
    "AGENT_ORDER",
]

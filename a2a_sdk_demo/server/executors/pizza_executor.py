"""Pizza Seller Executor — instant response pattern.

Implements AgentExecutor.execute() for pizza orders.
The SDK handles all JSON-RPC routing, task storage, and error responses.
"""

from __future__ import annotations

from a2a.server.agent_execution.agent_executor import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.types.a2a_pb2 import Message, Part, ROLE_AGENT

from a2a_sdk_demo.server.executors.utils import extract_text, choose_quantity


class PizzaExecutor(AgentExecutor):
    """Handles pizza orders. Returns instant responses."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Process a pizza order and enqueue the response."""
        user_text = extract_text(context.message)
        item = _choose_pizza(user_text)
        quantity = choose_quantity(user_text)
        total = quantity * 12  # $12 per pizza
        plural = "s" if quantity > 1 else ""

        reply = (
            f"Pizza Seller Agent confirmed: {quantity} {item}{plural}; "
            f"unit price $12; total ${total}; ready in 20 minutes."
        )

        await event_queue.enqueue_event(
            Message(role=ROLE_AGENT, parts=[Part(text=reply)])
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        pass  # Instant agent — nothing to cancel


# ── Business logic ───────────────────────────────────────────────────


def _choose_pizza(text: str) -> str:
    """Select pizza flavor from order text."""
    lower = text.lower()
    for flavor in ["veggie", "margherita", "pepperoni", "cheese", "mushroom"]:
        if flavor in lower:
            return f"{flavor} pizza"
    return "veggie pizza"

"""Burger Seller Executor — instant response pattern.

Same structure as PizzaExecutor but for burgers.
"""

from __future__ import annotations

from a2a.server.agent_execution.agent_executor import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.types.a2a_pb2 import Message, Part, ROLE_AGENT

from a2a_sdk_demo.server.executors.utils import extract_text, choose_quantity


class BurgerExecutor(AgentExecutor):
    """Handles burger orders. Returns instant responses."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Process a burger order and enqueue the response."""
        user_text = extract_text(context.message)
        item = _choose_burger(user_text)
        quantity = choose_quantity(user_text)
        total = quantity * 9  # $9 per burger
        plural = "s" if quantity > 1 else ""

        reply = (
            f"Burger Seller Agent confirmed: {quantity} {item}{plural}; "
            f"unit price $9; total ${total}; ready in 10 minutes."
        )

        await event_queue.enqueue_event(
            Message(role=ROLE_AGENT, parts=[Part(text=reply)])
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        pass  # Instant agent — nothing to cancel


# ── Business logic ───────────────────────────────────────────────────


def _choose_burger(text: str) -> str:
    """Select burger type from order text."""
    lower = text.lower()
    for burger in ["cheeseburger", "veggie burger", "classic burger", "chicken burger"]:
        if burger in lower:
            return burger
    if "veggie" in lower:
        return "veggie burger"
    return "cheeseburger"

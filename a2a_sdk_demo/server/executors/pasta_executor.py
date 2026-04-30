"""Pasta Seller Executor — streaming (SSE) response pattern.

Demonstrates A2A streaming: instead of returning a single response,
the executor enqueues multiple partial status updates that the SDK
streams to the client via SSE (Server-Sent Events).

The client receives tokens progressively, creating a "typing" effect.
"""

from __future__ import annotations

import asyncio

from a2a.server.agent_execution.agent_executor import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.types.a2a_pb2 import (
    Message,
    Part,
    ROLE_AGENT,
    TaskStatus,
    TaskState,
    TaskStatusUpdateEvent,
)

from a2a_sdk_demo.server.executors.utils import extract_text, choose_quantity


class PastaExecutor(AgentExecutor):
    """Handles pasta orders. Streams response word-by-word via SSE."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Process a pasta order and stream the response word-by-word."""
        user_text = extract_text(context.message)
        item = _choose_pasta(user_text)
        quantity = choose_quantity(user_text)
        total = quantity * 11  # $11 per pasta
        plural = "s" if quantity > 1 else ""

        full_reply = (
            f"Pasta Seller Agent confirmed: {quantity} {item}{plural}; "
            f"unit price $11; total ${total}; ready in 15 minutes."
        )

        # Stream word-by-word with partial status updates
        words = full_reply.split(" ")
        accumulated = ""
        for word in words:
            accumulated += (" " if accumulated else "") + word
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=context.task_id,
                    status=TaskStatus(
                        state=TaskState.TASK_STATE_WORKING,
                        message=Message(
                            role=ROLE_AGENT,
                            parts=[Part(text=accumulated)],
                        ),
                    ),
                )
            )
            await asyncio.sleep(0.15)  # Simulate streaming delay

        # Final complete message
        await event_queue.enqueue_event(
            Message(role=ROLE_AGENT, parts=[Part(text=full_reply)])
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                status=TaskStatus(state=TaskState.TASK_STATE_CANCELED),
            )
        )


# ── Business logic ───────────────────────────────────────────────────


def _choose_pasta(text: str) -> str:
    """Select pasta type from order text."""
    lower = text.lower()
    for pasta in ["penne", "spaghetti", "fettuccine", "linguine", "rigatoni", "carbonara", "alfredo"]:
        if pasta in lower:
            return f"{pasta} pasta"
    return "penne pasta"

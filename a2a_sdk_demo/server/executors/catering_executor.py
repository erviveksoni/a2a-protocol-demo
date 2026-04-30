"""Catering Planner Executor — long-running task pattern.

Demonstrates A2A's task lifecycle: the executor enqueues progress
status updates with delays, then finally enqueues a completed Task
with the artifact. The SDK's TaskStore + EventQueue handle the
lifecycle automatically.
"""

from __future__ import annotations

import asyncio
import re

from a2a.server.agent_execution.agent_executor import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.types.a2a_pb2 import (
    Artifact,
    Message,
    Part,
    ROLE_AGENT,
    TaskStatus,
    TaskState,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent,
)

from a2a_sdk_demo.server.executors.utils import extract_text


PROGRESS_STAGES = [
    "Checking menu options...",
    "Calculating per-person pricing...",
    "Estimating preparation time...",
    "Generating final quote...",
]


class CateringExecutor(AgentExecutor):
    """Plans catering orders. Demonstrates long-running tasks with progress."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Simulate long-running catering planning with status updates."""
        user_text = extract_text(context.message)

        # Send progress updates every 2 seconds
        for stage_msg in PROGRESS_STAGES:
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=context.task_id,
                    status=TaskStatus(
                        state=TaskState.TASK_STATE_WORKING,
                        message=Message(
                            role=ROLE_AGENT,
                            parts=[Part(text=stage_msg)],
                        ),
                    ),
                )
            )
            await asyncio.sleep(2)

        # Build the final catering quote
        quote = _build_catering_quote(user_text)

        # Enqueue artifact
        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                task_id=context.task_id,
                artifact=Artifact(
                    name="catering-quote",
                    parts=[Part(text=quote)],
                ),
            )
        )

        # Enqueue final completed status
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                status=TaskStatus(
                    state=TaskState.TASK_STATE_COMPLETED,
                    message=Message(
                        role=ROLE_AGENT,
                        parts=[Part(text=quote)],
                    ),
                ),
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                status=TaskStatus(state=TaskState.TASK_STATE_CANCELED),
            )
        )


# ── Business logic ───────────────────────────────────────────────────


def _build_catering_quote(user_text: str) -> str:
    lower = user_text.lower()
    match = re.search(r"(\d+)\s*people", lower)
    head_count = int(match.group(1)) if match else 20
    vegetarian = "vegetar" in lower or "veggie" in lower or "vegan" in lower

    items: list[str] = []
    total = 0

    if vegetarian:
        veggie_count = head_count // 2
        meat_count = head_count - veggie_count
        items.append(f"  - {veggie_count} veggie wraps @ $10 each = ${veggie_count * 10}")
        items.append(f"  - {meat_count} chicken burgers @ $9 each = ${meat_count * 9}")
        veggie_pizza = max(head_count // 4, 1)
        items.append(f"  - {veggie_pizza} large veggie pizzas @ $12 each = ${veggie_pizza * 12}")
        total = veggie_count * 10 + meat_count * 9 + veggie_pizza * 12
    else:
        burger_count = head_count // 2
        pizza_count = head_count - burger_count
        items.append(f"  - {pizza_count} assorted pizzas @ $12 each = ${pizza_count * 12}")
        items.append(f"  - {burger_count} classic burgers @ $9 each = ${burger_count * 9}")
        total = pizza_count * 12 + burger_count * 9

    prep_minutes = 60 + (head_count * 1.5)
    menu_text = "\n".join(items)
    return (
        f"Catering quote for {head_count} people:\n"
        f"{menu_text}\n"
        f"  Total: ${total}\n"
        f"  Ready in {int(prep_minutes)} minutes"
    )

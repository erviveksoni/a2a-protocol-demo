"""A2A SDK v1.0 Client Helpers — protocol-level functions.

This module handles all the A2A v1.0 protocol details:
  - Agent Card discovery
  - Sending messages via JSON-RPC (SendMessage)
  - Polling long-running tasks (GetTask)
  - Extracting text from SDK response formats

These are reusable across chat.py, run_all.py, or any other client.
None of this code knows about the terminal UI or LLM — it's pure A2A protocol.

Key SDK v1.0 requirements:
  - A2A-Version: 1.0 header on all requests
  - SendMessage method (PascalCase)
  - message_id required in messages
  - role: 1 (protobuf ROLE_USER enum)
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Callable

import httpx


# ── Protocol Constants ────────────────────────────────────────────────

A2A_HEADERS = {"A2A-Version": "1.0", "Content-Type": "application/json"}

AGENT_URLS = [
    "http://127.0.0.1:9001",  # Pizza
    "http://127.0.0.1:9002",  # Burger
    "http://127.0.0.1:9003",  # Catering
    "http://127.0.0.1:9004",  # Pasta (streaming)
]

# Skills that return long-running tasks (need polling)
LONG_RUNNING_SKILLS = {"plan_catering"}

# Skills that support streaming (SSE)
STREAMING_SKILLS = {"create_pasta_order"}


# ── Agent Discovery ──────────────────────────────────────────────────


async def discover_agents(
    agent_urls: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Fetch Agent Cards from all agents.

    Returns a list of dicts with the card data plus:
      _base_url:    the agent's base URL
      _jsonrpc_url: the JSON-RPC endpoint URL
    """
    urls = agent_urls or AGENT_URLS
    agents: list[dict[str, Any]] = []
    async with httpx.AsyncClient() as client:
        for url in urls:
            resp = await client.get(
                f"{url}/.well-known/agent-card.json", timeout=5
            )
            card = resp.json()
            card["_base_url"] = url
            card["_jsonrpc_url"] = f"{url}/a2a/jsonrpc"
            agents.append(card)
    return agents


# ── Response Text Extraction ─────────────────────────────────────────


def extract_reply_text(result: dict) -> str:
    """Extract text from an SDK JSON-RPC result.

    The SDK may nest the response in several ways:
      result.task.artifacts[0].parts[0].text   (completed task with artifact)
      result.task.status.message.parts[0].text (task status message)
      result.status.message.parts[0].text      (direct task)
      result.message.parts[0].text             (direct message)
    """
    # Unwrap "task" wrapper if present
    task = result.get("task", result)

    # 1. Check artifacts first (most specific for completed tasks)
    for artifact in task.get("artifacts", []):
        for part in artifact.get("parts", []):
            if isinstance(part, dict) and part.get("text"):
                return part["text"]

    # 2. Check task status message
    status = task.get("status", {})
    if isinstance(status, dict):
        msg = status.get("message", {})
        if isinstance(msg, dict):
            for part in msg.get("parts", []):
                if isinstance(part, dict) and part.get("text"):
                    return part["text"]

    # 3. Check direct message
    msg = result.get("message", {})
    if isinstance(msg, dict):
        for part in msg.get("parts", []):
            if isinstance(part, dict) and part.get("text"):
                return part["text"]

    # 4. Check direct parts
    for part in result.get("parts", []):
        if isinstance(part, dict) and part.get("text"):
            return part["text"]

    return str(result)[:100] + "..."


# ── Sending Messages ─────────────────────────────────────────────────


async def send_message(
    client: httpx.AsyncClient,
    jsonrpc_url: str,
    text: str,
    return_immediately: bool = False,
) -> dict:
    """Send a message using A2A v1.0 JSON-RPC format.

    Args:
        client:             An httpx async client.
        jsonrpc_url:        The agent's JSON-RPC endpoint.
        text:               The message text to send.
        return_immediately: If True, server returns task in "working" state
                           immediately (for long-running agents).

    Returns:
        The raw JSON-RPC result dict.
    """
    params: dict[str, Any] = {
        "message": {
            "role": 1,  # ROLE_USER in protobuf
            "message_id": str(uuid.uuid4()),
            "parts": [{"text": text}],
        },
    }
    if return_immediately:
        params["configuration"] = {"return_immediately": True}

    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "SendMessage",
        "params": params,
    }
    resp = await client.post(
        jsonrpc_url, json=payload, headers=A2A_HEADERS, timeout=30
    )
    body = resp.json()
    if "error" in body:
        raise RuntimeError(f"JSON-RPC error: {body['error']}")
    return body.get("result", {})


# ── Task Polling ─────────────────────────────────────────────────────


async def poll_task(
    client: httpx.AsyncClient,
    jsonrpc_url: str,
    task_id: str,
    on_progress: Callable[[str], None] | None = None,
    poll_interval: float = 2.0,
    max_polls: int = 20,
) -> str:
    """Poll GetTask until the task completes, returning artifact text.

    Shows live progress via the on_progress callback.

    Args:
        client:        An httpx async client.
        jsonrpc_url:   The agent's JSON-RPC endpoint.
        task_id:       The task ID from send_message().
        on_progress:   Called with each new status message.
        poll_interval: Seconds between polls.
        max_polls:     Maximum polls before timeout.

    Returns:
        The artifact/completion text.
    """
    seen: set[str] = set()

    for _ in range(max_polls):
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "GetTask",
            "params": {"id": task_id},
        }
        resp = await client.post(
            jsonrpc_url, json=payload, headers=A2A_HEADERS, timeout=10
        )
        body = resp.json()
        if "error" in body:
            raise RuntimeError(f"GetTask error: {body['error']}")

        result = body.get("result", {})
        task = result.get("task", result)
        status = task.get("status", {})
        state = status.get("state", "")

        # Extract and report progress messages
        msg = status.get("message", {})
        if isinstance(msg, dict):
            for part in msg.get("parts", []):
                if isinstance(part, dict) and part.get("text"):
                    txt = part["text"]
                    if txt not in seen and on_progress:
                        seen.add(txt)
                        # Support both sync and async callbacks
                        result_cb = on_progress(txt)
                        if asyncio.iscoroutine(result_cb):
                            await result_cb

        # Check terminal states
        if "COMPLETED" in state:
            return extract_reply_text(result)
        if "CANCELED" in state or "FAILED" in state:
            raise RuntimeError(
                f"Task {state}: {extract_reply_text(result)}"
            )

        await asyncio.sleep(poll_interval)

    raise RuntimeError(f"Task {task_id} timed out after {max_polls} polls")


# ── Helpers ──────────────────────────────────────────────────────────


def is_long_running(agent: dict) -> bool:
    """Check if an agent's skills include long-running operations."""
    return any(
        s.get("id") in LONG_RUNNING_SKILLS
        for s in agent.get("skills", [])
    )


def is_streaming(agent: dict) -> bool:
    """Check if an agent supports streaming (SSE) responses."""
    # Check capabilities from agent card
    caps = agent.get("capabilities", {})
    if isinstance(caps, dict) and caps.get("streaming"):
        return True
    # Fallback: check skills
    return any(
        s.get("id") in STREAMING_SKILLS
        for s in agent.get("skills", [])
    )


async def send_message_stream(
    client: httpx.AsyncClient,
    base_url: str,
    text: str,
    on_token: Callable[[str], Any] | None = None,
) -> str:
    """Send a message via the REST streaming endpoint (SSE).

    POSTs to /message:stream and yields partial text as SSE events arrive.

    Args:
        client:    An httpx async client.
        base_url:  The agent's base URL (e.g. http://127.0.0.1:9004).
        text:      The message text to send.
        on_token:  Called with each new partial text chunk.

    Returns:
        The final complete response text.
    """
    import json as _json

    payload = {
        "message": {
            "role": "ROLE_USER",
            "messageId": str(uuid.uuid4()),
            "parts": [{"text": text}],
        },
    }

    url = f"{base_url}/message:stream"
    headers = {**A2A_HEADERS}  # Includes A2A-Version: 1.0
    last_text = ""

    async with client.stream(
        "POST", url, json=payload, headers=headers, timeout=30
    ) as response:
        buffer = ""
        async for raw_chunk in response.aiter_bytes():
            # Decode and normalize line endings (SSE uses \r\n)
            buffer += raw_chunk.decode("utf-8", errors="replace")
            # SSE events are separated by \r\n\r\n or \n\n
            while "\r\n\r\n" in buffer or "\n\n" in buffer:
                # Find the earliest separator
                idx_rn = buffer.find("\r\n\r\n")
                idx_n = buffer.find("\n\n")
                if idx_rn >= 0 and (idx_n < 0 or idx_rn <= idx_n):
                    event_str = buffer[:idx_rn]
                    buffer = buffer[idx_rn + 4:]
                else:
                    event_str = buffer[:idx_n]
                    buffer = buffer[idx_n + 2:]

                data_line = ""
                for line in event_str.split("\n"):
                    line = line.strip()
                    if line.startswith("data:"):
                        data_line = line[5:].strip()

                if not data_line:
                    continue

                try:
                    event_data = _json.loads(data_line)
                except _json.JSONDecodeError:
                    continue

                # Extract text from various event shapes
                text_val = _extract_stream_text(event_data)
                if text_val and text_val != last_text:
                    last_text = text_val
                    if on_token:
                        result_cb = on_token(text_val)
                        if asyncio.iscoroutine(result_cb):
                            await result_cb

    return last_text


def get_task_id(result: dict) -> str:
    """Extract the task_id from a SendMessage result."""
    task = result.get("task", result)
    return task.get("id", "")


def _extract_stream_text(event: dict) -> str:
    """Extract text from a streaming SSE event.

    Events may be Task, TaskStatusUpdateEvent, or Message shaped.
    """
    # TaskStatusUpdateEvent shape: {statusUpdate: {status: {message: {parts: [...]}}}}
    # SDK uses "statusUpdate" (confirmed by raw SSE output)
    for key in ("statusUpdate", "taskStatus"):
        ts = event.get(key, {})
        if ts:
            status = ts.get("status", {})
            msg = status.get("message", {})
            if isinstance(msg, dict):
                for part in msg.get("parts", []):
                    if isinstance(part, dict) and part.get("text"):
                        return part["text"]

    # Message shape: {message: {parts: [...]}}
    msg = event.get("message", {})
    if isinstance(msg, dict):
        for part in msg.get("parts", []):
            if isinstance(part, dict) and part.get("text"):
                return part["text"]

    # Task shape: {task: {status: {message: {parts: [...]}}}}
    task = event.get("task", {})
    if task:
        return extract_reply_text(task)

    # Direct parts
    for part in event.get("parts", []):
        if isinstance(part, dict) and part.get("text"):
            return part["text"]

    return ""

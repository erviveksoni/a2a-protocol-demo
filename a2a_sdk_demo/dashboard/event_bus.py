"""SSE Event Bus — emits events for the visualization dashboard.

A lightweight pub/sub system that:
  1. Accepts events from chat.py via emit()
  2. Streams them to the browser via Server-Sent Events (SSE)

The dashboard connects to GET /events and receives a real-time stream
of everything happening in the A2A flow.

Usage:
    # In chat.py:
    from a2a_sdk_demo.dashboard.event_bus import emit, start_dashboard

    start_dashboard(port=8080)  # Starts in background thread
    await emit("discover", {"agents": [...]})
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from sse_starlette.sse import EventSourceResponse

# ── Event Bus ─────────────────────────────────────────────────────────

_subscribers: list[asyncio.Queue] = []
_event_history: list[dict] = []
_loop: asyncio.AbstractEventLoop | None = None

app = FastAPI(title="A2A Flow Visualizer")


async def emit(event_type: str, data: dict[str, Any]) -> None:
    """Emit an event to all connected dashboard browsers.

    Call this from chat.py at each orchestration step.
    Safe to call even if no dashboard is connected.
    """
    event = {
        "event": event_type,
        "data": json.dumps({
            "type": event_type,
            "timestamp": time.time(),
            **data,
        }),
    }
    _event_history.append(event)

    # Deliver to all SSE subscribers
    dead: list[asyncio.Queue] = []
    for q in _subscribers:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        _subscribers.remove(q)


def emit_sync(event_type: str, data: dict[str, Any]) -> None:
    """Synchronous version for non-async contexts."""
    event = {
        "event": event_type,
        "data": json.dumps({
            "type": event_type,
            "timestamp": time.time(),
            **data,
        }),
    }
    _event_history.append(event)
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except (asyncio.QueueFull, Exception):
            pass


# ── SSE Endpoint ──────────────────────────────────────────────────────


@app.get("/events")
async def sse_stream():
    """SSE endpoint — browser connects here to receive live events."""
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _subscribers.append(q)

    async def generator():
        try:
            # Send history first so late-joining browsers catch up
            for event in _event_history:
                yield event
            # Then stream live events
            while True:
                event = await q.get()
                yield event
        except asyncio.CancelledError:
            pass
        finally:
            if q in _subscribers:
                _subscribers.remove(q)

    return EventSourceResponse(generator())


# ── Receive Events from External Processes ────────────────────────────

from fastapi import Request as FastAPIRequest


@app.post("/emit")
async def receive_event(request: FastAPIRequest):
    """Receive an event from chat.py (running in another process)."""
    body = await request.json()
    event_type = body.get("type", "unknown")
    event = {
        "event": event_type,
        "data": json.dumps(body),
    }
    _event_history.append(event)
    dead: list[asyncio.Queue] = []
    for q in _subscribers:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        _subscribers.remove(q)
    return {"ok": True}


# ── Browser Chat API ──────────────────────────────────────────────────

import subprocess
import sys

_agent_procs: list[subprocess.Popen] = []
_agents_discovered: list[dict] = []
_ROOT = Path(__file__).resolve().parents[2]  # project root


def _wait_for_url(url: str, timeout: int = 15) -> None:
    import httpx as _hx
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = _hx.get(url, timeout=1)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.3)


@app.post("/api/start")
async def api_start_agents():
    """Start all 4 A2A agents and discover them. Called from browser."""
    global _agents_discovered
    python = sys.executable

    # Emit startup event
    await emit("startup", {"message": "Starting agents on ports 9001-9004..."})

    for kind, port in [("pizza", "9001"), ("burger", "9002"), ("catering", "9003"), ("pasta", "9004")]:
        _agent_procs.append(subprocess.Popen(
            [python, "-m", "a2a_sdk_demo.server.agent_server", "--kind", kind, "--port", port],
            cwd=_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ))

    # Wait for agents
    for url in ["http://127.0.0.1:9001", "http://127.0.0.1:9002", "http://127.0.0.1:9003", "http://127.0.0.1:9004"]:
        _wait_for_url(f"{url}/.well-known/agent-card.json")

    # Discover agents
    from a2a_sdk_demo.client.sdk_client import discover_agents
    _agents_discovered = await discover_agents()

    # Send rich discover data with skills
    agent_details = []
    for a in _agents_discovered:
        skills = a.get("skills", [])
        agent_details.append({
            "name": a["name"],
            "url": a.get("_base_url", ""),
            "skills": [
                {"id": s.get("id", ""), "description": s.get("description", ""), "tags": s.get("tags", [])}
                for s in skills
            ],
        })
    await emit("discover", {"agents": [a["name"] for a in _agents_discovered], "details": agent_details})

    return {"ok": True, "agents": [a["name"] for a in _agents_discovered]}


@app.post("/api/chat")
async def api_chat(request: FastAPIRequest):
    """Process a chat message from the browser. Runs the full LLM flow."""
    body = await request.json()
    user_text = body.get("text", "")
    if not user_text:
        return {"error": "No text provided"}

    if not _agents_discovered:
        return {"error": "Agents not started. Click 'Start Agents' first."}

    # Emit user event
    await emit("user", {"text": user_text})
    await emit("llm_thinking", {"message": "Planning delegations..."})

    # Run the LLM planner
    from a2a_sdk_demo.client.llm_planner import create_llm_client, plan_delegations, summarize_results
    from a2a_sdk_demo.client.sdk_client import (
        send_message, extract_reply_text, is_long_running, is_streaming,
        get_task_id, poll_task, send_message_stream,
    )
    import httpx as _hx

    llm = create_llm_client()
    plans = plan_delegations(llm, _agents_discovered, user_text)

    if not plans:
        return {"summary": "I couldn't figure out what to order. Could you be more specific?"}

    await emit("plan_result", {"delegations": [p.agent_name for p in plans]})
    agent_map = {a["name"]: a for a in _agents_discovered}

    delegations: list[tuple[str, str, str]] = []
    async with _hx.AsyncClient() as client:
        for plan in plans:
            agent = agent_map.get(plan.agent_name)
            if not agent:
                delegations.append((plan.agent_name, plan.order_text, "Agent not found"))
                continue
            try:
                _skill = plan.skill_id if hasattr(plan, 'skill_id') else ''
                await emit("send", {"agent": agent["name"], "text": plan.order_text, "skill_id": _skill})

                if is_streaming(agent):
                    async def on_token(text: str, _agent=agent, _sid=_skill) -> None:
                        await emit("streaming", {"agent": _agent["name"], "text": text, "skill_id": _sid})

                    reply = await send_message_stream(
                        client, agent["_base_url"], plan.order_text, on_token=on_token
                    )
                elif is_long_running(agent):
                    result = await send_message(client, agent["_jsonrpc_url"], plan.order_text, return_immediately=True)
                    task_id = get_task_id(result)
                    await emit("working", {"agent": agent["name"], "task_id": task_id})

                    async def on_progress(msg: str) -> None:
                        await emit("progress", {"agent": agent["name"], "message": msg})

                    reply = await poll_task(client, agent["_jsonrpc_url"], task_id, on_progress=on_progress)
                else:
                    result = await send_message(client, agent["_jsonrpc_url"], plan.order_text)
                    reply = extract_reply_text(result)

                await emit("complete", {"agent": agent["name"], "reply": reply.split("\n")[0], "skill_id": _skill})
                delegations.append((plan.agent_name, plan.order_text, reply))
            except Exception as exc:
                await emit("error", {"agent": plan.agent_name, "error": str(exc)})
                delegations.append((plan.agent_name, plan.order_text, f"Error: {exc}"))

    summary = summarize_results(llm, user_text, delegations)
    await emit("summary", {"text": summary})
    return {"summary": summary}


@app.post("/api/clear")
async def api_clear():
    """Clear event history. Called from the browser Clear button."""
    _event_history.clear()
    return {"ok": True}


@app.on_event("shutdown")
def shutdown_agents():
    for p in _agent_procs:
        p.terminate()


# ── Dashboard HTML ────────────────────────────────────────────────────

DASHBOARD_PATH = Path(__file__).parent / "dashboard.html"


@app.get("/")
async def dashboard():
    """Serve the visualization dashboard."""
    if DASHBOARD_PATH.exists():
        return FileResponse(DASHBOARD_PATH, media_type="text/html")
    return HTMLResponse("<h1>dashboard.html not found</h1>")


# ── Background Server ─────────────────────────────────────────────────


def start_dashboard(port: int = 8080) -> None:
    """Start the dashboard server in a background thread."""

    def _run():
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

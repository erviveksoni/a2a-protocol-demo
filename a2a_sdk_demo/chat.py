"""Interactive Chat — Terminal UI for the A2A Lunch Concierge.

This file handles ONLY the terminal user interface:
  - Banner, help, agent display
  - Background agent process management
  - Chat loop with input/output
  - Order processing orchestration (calls sdk_client + llm_planner)

All A2A protocol details live in client/sdk_client.py.
All LLM logic lives in client/llm_planner.py.

Usage:
    python -m a2a_sdk_demo.chat
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from pathlib import Path

import httpx

from a2a_sdk_demo.client.llm_planner import (
    BedrockLLM,
    create_llm_client,
    plan_delegations,
    summarize_results,
)
from a2a_sdk_demo.client.sdk_client import (
    AGENT_URLS,
    discover_agents,
    extract_reply_text,
    get_task_id,
    is_long_running,
    is_streaming,
    poll_task,
    send_message,
    send_message_stream,
)

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_URL = "http://127.0.0.1:8080"

# ── ANSI colors ───────────────────────────────────────────────────────

BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
RED = "\033[31m"
RESET = "\033[0m"


# ── Dashboard Event Emitter ───────────────────────────────────────────


async def emit_to_dashboard(event_type: str, data: dict) -> None:
    """Send an event to the dashboard server (if running in another terminal).

    This is a fire-and-forget call — if the dashboard isn't running,
    the error is silently ignored.
    """
    try:
        async with httpx.AsyncClient() as c:
            await c.post(
                f"{DASHBOARD_URL}/emit",
                json={"type": event_type, "timestamp": time.time(), **data},
                timeout=1,
            )
    except Exception:
        pass  # Dashboard not running — that's fine


# ── Terminal UI ──────────────────────────────────────────────────────


def _print_banner() -> None:
    print(f"""
{CYAN}{BOLD}╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   🍕  A2A Lunch Concierge  🍔                               ║
║                                                              ║
║   Powered by Amazon Bedrock + Official A2A SDK               ║
║                                                              ║
║   Commands:  /help  /agents  /quit                           ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝{RESET}
""")


def _print_help() -> None:
    print(f"""
{BOLD}Example orders:{RESET}
  {DIM}• "Get me lunch for two people under $30. One person is vegetarian."
  • "Plan lunch for 20 people, include vegetarian options."
  • "Order three pepperoni pizzas for the team."{RESET}
""")


def _print_agents(agents: list[dict]) -> None:
    print(f"\n{BOLD}Discovered A2A Agents:{RESET}")
    for agent in agents:
        print(f"  {GREEN}●{RESET} {BOLD}{agent['name']}{RESET} @ {DIM}{agent['_base_url']}{RESET}")
        for skill in agent.get("skills", []):
            print(f"    ├─ {CYAN}{skill.get('id', '?')}{RESET}: {skill.get('description', '')}")
            tags = skill.get("tags", [])
            if tags:
                print(f"    └─ tags: {DIM}{', '.join(tags)}{RESET}")
    print()


# ── Background Agent Management ──────────────────────────────────────


def _wait_for(url: str, timeout_seconds: int = 15) -> None:
    """Block until a URL returns 200 (used to wait for agent startup)."""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=1)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.3)
    raise RuntimeError(f"Timed out waiting for {url}")


def start_agents() -> list[subprocess.Popen]:
    """Start all 4 A2A agents as background processes."""
    python = sys.executable
    agent_kinds = [("pizza", "9001"), ("burger", "9002"), ("catering", "9003"), ("pasta", "9004")]
    procs = []
    for kind, port in agent_kinds:
        procs.append(subprocess.Popen(
            [python, "-m", "a2a_sdk_demo.server.agent_server", "--kind", kind, "--port", port],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ))
    print(f"  {DIM}Starting agents (pizza, burger, catering, pasta)...{RESET}", end="", flush=True)
    for url in AGENT_URLS:
        _wait_for(f"{url}/.well-known/agent-card.json")
    print(f" {GREEN}✓{RESET}")
    return procs


def stop_agents(procs: list[subprocess.Popen]) -> None:
    """Terminate all background agent processes."""
    for p in procs:
        p.terminate()
    for p in procs:
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()


# ── Order Processing (orchestration) ─────────────────────────────────


async def process_order(
    llm: BedrockLLM,
    agents: list[dict],
    user_request: str,
) -> str:
    """Orchestrate: LLM plans → A2A delegates → LLM summarizes."""

    # Step 1: LLM plans which agents to call
    print(f"\n  {DIM}🧠 Thinking...{RESET}", flush=True)
    await emit_to_dashboard("user", {"text": user_request})
    await emit_to_dashboard("llm_thinking", {"message": "Planning delegations..."})
    plans = plan_delegations(llm, agents, user_request)

    if not plans:
        return "I couldn't figure out what to order. Could you be more specific?"

    await emit_to_dashboard("plan_result", {"delegations": [p.agent_name for p in plans]})
    agent_map = {a["name"]: a for a in agents}

    print(f"  {DIM}📡 Delegating to {len(plans)} agent(s)...{RESET}", flush=True)
    for plan in plans:
        print(f"     {YELLOW}→{RESET} {plan.agent_name} [{plan.skill_id}]: {DIM}{plan.order_text}{RESET}")

    # Step 2: Send to agents via A2A (sdk_client handles protocol)
    delegations: list[tuple[str, str, str]] = []
    async with httpx.AsyncClient() as client:
        for plan in plans:
            agent = agent_map.get(plan.agent_name)
            if not agent:
                delegations.append((plan.agent_name, plan.order_text, "⚠️ Agent not found"))
                continue
            try:
                skill = plan.skill_id
                if is_streaming(agent):
                    reply = await _handle_streaming(client, agent, plan.order_text, skill)
                elif is_long_running(agent):
                    reply = await _handle_long_running(client, agent, plan.order_text, skill)
                else:
                    reply = await _handle_instant(client, agent, plan.order_text, skill)
                delegations.append((plan.agent_name, plan.order_text, reply))
            except Exception as exc:
                delegations.append((plan.agent_name, plan.order_text, f"Error: {exc}"))
                print(f"     {RED}✗{RESET} {plan.agent_name}: {RED}{exc}{RESET}")

    # Step 3: LLM summarizes
    print(f"  {DIM}📝 Preparing summary...{RESET}", flush=True)
    return summarize_results(llm, user_request, delegations)


async def _handle_streaming(
    client: httpx.AsyncClient, agent: dict, order_text: str, skill_id: str = ""
) -> str:
    """Handle streaming agents (pasta) — SSE token-by-token response."""
    await emit_to_dashboard("send", {"agent": agent["name"], "text": order_text, "skill_id": skill_id})
    print(f"     {MAGENTA}🔤{RESET} {agent['name']}: {DIM}", end="", flush=True)

    last_printed = ""

    async def on_token(text: str) -> None:
        nonlocal last_printed
        new_chars = text[len(last_printed):]
        if new_chars:
            print(f"{new_chars}", end="", flush=True)
            last_printed = text
        await emit_to_dashboard("streaming", {"agent": agent["name"], "text": text, "skill_id": skill_id})

    reply = await send_message_stream(client, agent["_base_url"], order_text, on_token=on_token)
    print(f"{RESET}")
    first_line = reply.split("\n")[0]
    await emit_to_dashboard("complete", {"agent": agent["name"], "reply": first_line, "skill_id": skill_id})
    print(f"     {GREEN}✓{RESET} {agent['name']}: {DIM}{first_line}{RESET}")
    return reply


async def _handle_instant(
    client: httpx.AsyncClient, agent: dict, order_text: str, skill_id: str = ""
) -> str:
    """Handle instant agents (pizza, burger) — blocking SendMessage."""
    await emit_to_dashboard("send", {"agent": agent["name"], "text": order_text, "skill_id": skill_id})
    result = await send_message(client, agent["_jsonrpc_url"], order_text)
    reply = extract_reply_text(result)
    first_line = reply.split("\n")[0]
    await emit_to_dashboard("complete", {"agent": agent["name"], "reply": first_line, "skill_id": skill_id})
    print(f"     {GREEN}✓{RESET} {agent['name']}: {DIM}{first_line}{RESET}")
    return reply


async def _handle_long_running(
    client: httpx.AsyncClient, agent: dict, order_text: str, skill_id: str = ""
) -> str:
    """Handle long-running agents (catering) — return_immediately + poll."""
    await emit_to_dashboard("send", {"agent": agent["name"], "text": order_text, "skill_id": skill_id})
    result = await send_message(
        client, agent["_jsonrpc_url"], order_text, return_immediately=True
    )
    task_id = get_task_id(result)
    await emit_to_dashboard("working", {"agent": agent["name"], "task_id": task_id, "skill_id": skill_id})
    print(f"     {MAGENTA}⏳{RESET} {agent['name']}: {DIM}working (task_id={task_id})...{RESET}")

    async def on_progress(msg: str) -> None:
        await emit_to_dashboard("progress", {"agent": agent["name"], "message": msg})
        print(f"        {DIM}├ {msg}{RESET}")

    reply = await poll_task(client, agent["_jsonrpc_url"], task_id, on_progress=on_progress)
    first_line = reply.split("\n")[0]
    await emit_to_dashboard("complete", {"agent": agent["name"], "reply": first_line, "skill_id": skill_id})
    print(f"     {GREEN}✓{RESET} {agent['name']}: {DIM}{first_line}{RESET}")
    return reply


# ── Main Chat Loop ───────────────────────────────────────────────────


def main() -> None:
    _print_banner()

    # Initialize Bedrock LLM
    print(f"  {DIM}Connecting to Amazon Bedrock...{RESET}", end="", flush=True)
    try:
        llm = create_llm_client()
        print(f" {GREEN}✓{RESET}")
    except RuntimeError as exc:
        print(f" {RED}✗{RESET}\n{RED}{exc}{RESET}")
        sys.exit(1)

    # Start background agents
    procs = start_agents()

    try:
        # Discover agents via Agent Cards
        print(f"  {DIM}Discovering A2A agents...{RESET}", end="", flush=True)
        agents = asyncio.run(discover_agents())
        print(f" {GREEN}✓{RESET} Found {len(agents)} agents")
        _print_agents(agents)

        print(f"{BOLD}Ready! Type your lunch order:{RESET}\n")

        # Chat loop
        while True:
            try:
                user_input = input(f"{BOLD}{CYAN}You ❯{RESET} ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not user_input:
                continue
            lower = user_input.lower()
            if lower in ("/quit", "/exit", "/q", "quit", "exit"):
                print(f"\n{DIM}Bon appétit! 👋{RESET}\n")
                break
            elif lower in ("/help", "/h", "help"):
                _print_help()
                continue
            elif lower in ("/agents", "/a"):
                _print_agents(agents)
                continue

            try:
                summary = asyncio.run(process_order(llm, agents, user_input))
                print(f"\n{BOLD}{GREEN}🍽️  Concierge:{RESET} {summary}\n")
            except Exception as exc:
                print(f"\n{RED}Error: {exc}{RESET}\n")

    finally:
        print(f"  {DIM}Shutting down agents...{RESET}", end="", flush=True)
        stop_agents(procs)
        print(f" {GREEN}✓{RESET}")


if __name__ == "__main__":
    main()

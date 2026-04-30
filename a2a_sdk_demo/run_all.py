"""Deterministic Demo — runs all 4 agents and tests them.

Starts all 4 agents (pizza, burger, catering, pasta), discovers their
Agent Cards, and sends a test order to each instant agent.

Usage:
    python -m a2a_sdk_demo.run_all
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from pathlib import Path

import httpx

from a2a_sdk_demo.client.sdk_client import (
    AGENT_URLS,
    discover_agents,
    extract_reply_text,
    send_message,
)

ROOT = Path(__file__).resolve().parents[1]

AGENT_CONFIGS = [
    ("http://127.0.0.1:9001", "pizza"),
    ("http://127.0.0.1:9002", "burger"),
    ("http://127.0.0.1:9003", "catering"),
    ("http://127.0.0.1:9004", "pasta"),
]


def wait_for(url: str, timeout_seconds: int = 15) -> None:
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


async def run_demo() -> None:
    """Simple deterministic test of all 4 agents."""
    # Discover agents
    agents = await discover_agents()
    print("\nDiscovered A2A agents:")
    for agent in agents:
        skills = ", ".join(s.get("id", "?") for s in agent.get("skills", []))
        print(f"  - {agent['name']} @ {agent['_base_url']}")
        print(f"    skills: {skills}")

    # Send instant orders using sdk_client (skip catering — it's long-running)
    async with httpx.AsyncClient() as client:
        for agent in agents:
            skill_ids = {s.get("id") for s in agent.get("skills", [])}

            # Skip long-running agents in the deterministic demo
            if "plan_catering" in skill_ids:
                continue

            # Determine agent kind and appropriate order
            if "create_pizza_order" in skill_ids:
                kind = "pizza"
                order_text = "Order one veggie pizza"
            elif "create_pasta_order" in skill_ids:
                kind = "pasta"
                order_text = "Order one penne pasta"
            else:
                kind = "burger"
                order_text = "Order one cheeseburger"

            result = await send_message(client, agent["_jsonrpc_url"], order_text)
            text = extract_reply_text(result)
            print(f"\n  {kind.title()} response: {text}")

    print("\n✓ Demo complete!")


def main() -> None:
    python = sys.executable
    procs: list[subprocess.Popen] = []
    try:
        for url, kind in AGENT_CONFIGS:
            port = url.split(":")[-1]
            procs.append(
                subprocess.Popen(
                    [python, "-m", "a2a_sdk_demo.server.agent_server", "--kind", kind, "--port", port],
                    cwd=ROOT,
                )
            )

        for url in AGENT_URLS:
            wait_for(f"{url}/.well-known/agent-card.json")

        asyncio.run(run_demo())
    finally:
        for proc in procs:
            proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    main()

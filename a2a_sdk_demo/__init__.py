"""A2A Lunch Concierge — Official SDK Implementation.

A teaching-focused demo of the Agent-to-Agent (A2A) protocol using
the official a2a-sdk package.

Package structure (grouped by concern):

  server/            — Agent servers (SDK-wired FastAPI + AgentExecutors)
    agent_server.py      Creates FastAPI app using SDK routes
    executors/           Pizza, Burger, Pasta, Catering executor implementations

  client/            — A2A protocol helpers + LLM planning
    sdk_client.py        discover, send, poll, extract (pure A2A v1.0)
    llm_planner.py       Bedrock LLM for smart delegation planning

  dashboard/         — Live visualization (SSE-based)
    event_bus.py         SSE server + POST /emit for cross-process events
    dashboard_server.py  Standalone launcher (start this first)
    dashboard.html       Animated browser UI

  chat.py            — Terminal UI + orchestration (entry point)
  run_all.py         — Deterministic demo (no LLM, no dashboard)

Entry points:
  python -m a2a_sdk_demo.run_all                    — Deterministic demo
  python -m a2a_sdk_demo.chat                       — Interactive LLM chat
  python -m a2a_sdk_demo.dashboard.dashboard_server — Dashboard (start first)
"""

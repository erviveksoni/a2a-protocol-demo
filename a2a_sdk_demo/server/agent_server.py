"""A2A Agent Server — creates a FastAPI app for any agent kind.

The SDK's create_jsonrpc_routes() and create_rest_routes() auto-wire
all A2A protocol endpoints from an AgentExecutor implementation.

This module:
  1. Defines agent configurations (name, skills, executor class)
  2. Builds typed AgentCards (protobuf)
  3. Creates a FastAPI app with SDK-generated routes

Usage:
    python -m a2a_sdk_demo.server.agent_server --kind pizza --port 9001
    python -m a2a_sdk_demo.server.agent_server --kind burger --port 9002
    python -m a2a_sdk_demo.server.agent_server --kind catering --port 9003
    python -m a2a_sdk_demo.server.agent_server --kind pasta --port 9004
"""

from __future__ import annotations

import argparse
from typing import Any

import uvicorn
from fastapi import FastAPI
from starlette.routing import Route

from a2a.server.agent_execution.agent_executor import AgentExecutor
from a2a.server.events.in_memory_queue_manager import InMemoryQueueManager
from a2a.server.request_handlers.default_request_handler import LegacyRequestHandler
from a2a.server.routes import create_jsonrpc_routes, create_rest_routes
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.types.a2a_pb2 import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
)

from a2a_sdk_demo.server.executors.pizza_executor import PizzaExecutor
from a2a_sdk_demo.server.executors.burger_executor import BurgerExecutor
from a2a_sdk_demo.server.executors.catering_executor import CateringExecutor
from a2a_sdk_demo.server.executors.pasta_executor import PastaExecutor


# ── Agent Card definitions ────────────────────────────────────────────

AGENT_CONFIGS = {
    "pizza": {
        "name": "Pizza Seller Agent",
        "description": "A local A2A seller agent that confirms pizza orders.",
        "skills": [
            AgentSkill(
                id="create_pizza_order",
                name="Create pizza order",
                description="Confirms pizza orders with price and pickup time.",
                tags=["food", "pizza", "order"],
                examples=["Order one veggie pizza", "Can you make a margherita pizza?"],
            )
        ],
        "executor_cls": PizzaExecutor,
    },
    "burger": {
        "name": "Burger Seller Agent",
        "description": "A local A2A seller agent that confirms burger orders.",
        "skills": [
            AgentSkill(
                id="create_burger_order",
                name="Create burger order",
                description="Confirms burger orders with price and pickup time.",
                tags=["food", "burger", "order"],
                examples=["Order one cheeseburger", "Can you make a veggie burger?"],
            )
        ],
        "executor_cls": BurgerExecutor,
    },
    "catering": {
        "name": "Catering Planner Agent",
        "description": "Plans catering orders. Returns long-running tasks with progress updates.",
        "skills": [
            AgentSkill(
                id="plan_catering",
                name="Plan catering order",
                description="Plans large catering orders with menu selection, pricing, and preparation time.",
                tags=["food", "catering", "planning", "large-order"],
                examples=[
                    "Plan lunch for 20 people with vegetarian options",
                    "Cater a team event for 50 people",
                ],
            ),
            AgentSkill(
                id="dietary_menu",
                name="Dietary menu planning",
                description="Creates menus accommodating dietary restrictions like vegan, gluten-free, or halal.",
                tags=["dietary", "vegan", "gluten-free", "menu"],
                examples=[
                    "Plan a vegan lunch for 15 people",
                    "Create a gluten-free menu for the office",
                ],
            ),
        ],
        "executor_cls": CateringExecutor,
    },
    "pasta": {
        "name": "Pasta Seller Agent",
        "description": "A local A2A seller agent that confirms pasta orders. Supports streaming responses.",
        "skills": [
            AgentSkill(
                id="create_pasta_order",
                name="Create pasta order",
                description="Confirms pasta orders with price and pickup time. Streams response progressively.",
                tags=["food", "pasta", "order", "streaming"],
                examples=["Order two penne pastas", "Can you make a spaghetti carbonara?"],
            )
        ],
        "executor_cls": PastaExecutor,
        "streaming": True,
    },
}


def build_agent_card(kind: str, host: str, port: int) -> AgentCard:
    """Build a typed AgentCard (SDK protobuf) for the given agent kind."""
    config = AGENT_CONFIGS[kind]
    base_url = f"http://{host}:{port}"
    return AgentCard(
        name=config["name"],
        description=config["description"],
        version="0.2.0",
        capabilities=AgentCapabilities(
            streaming=bool(config.get("streaming", False)),
            push_notifications=False,
        ),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=config["skills"],
        supported_interfaces=[
            AgentInterface(
                url=f"{base_url}/a2a/jsonrpc",
                protocol_binding="JSONRPC",
                protocol_version="1.0.0",
            )
        ],
    )


def make_sdk_app(kind: str, host: str, port: int) -> FastAPI:
    """Create a FastAPI app using the SDK's route wiring.

    Steps:
      1. Instantiate the AgentExecutor for the given kind
      2. Create a LegacyRequestHandler with the executor + task store + card
      3. Let create_jsonrpc_routes() build the FastAPI routes
    """
    config = AGENT_CONFIGS[kind]
    executor: AgentExecutor = config["executor_cls"]()
    agent_card = build_agent_card(kind, host, port)
    task_store = InMemoryTaskStore()
    queue_manager = InMemoryQueueManager()

    # The SDK's request handler wires everything together
    request_handler = LegacyRequestHandler(
        agent_executor=executor,
        task_store=task_store,
        agent_card=agent_card,
        queue_manager=queue_manager,
    )

    # SDK auto-generates the routes
    jsonrpc_routes = create_jsonrpc_routes(
        request_handler, rpc_url="/a2a/jsonrpc", enable_v0_3_compat=False,
    )
    rest_routes = create_rest_routes(request_handler)

    from starlette.responses import JSONResponse
    from google.protobuf.json_format import MessageToDict

    card_dict = MessageToDict(agent_card, preserving_proto_field_name=True)

    app = FastAPI(title=config["name"])

    # Add our custom routes FIRST (before SDK routes, so they match before /{tenant})
    @app.get("/.well-known/agent-card.json")
    async def agent_card_endpoint() -> Any:
        return JSONResponse(content=card_dict)

    @app.get("/.well-known/agent.json")
    async def legacy_card() -> Any:
        return JSONResponse(content=card_dict)

    @app.get("/")
    async def root() -> dict[str, str]:
        return {
            "service": config["name"],
            "version": "0.2.0",
            "agent_card": "/.well-known/agent-card.json",
            "jsonrpc": "/a2a/jsonrpc",
        }

    # Mount SDK-generated routes AFTER our custom routes
    for route in jsonrpc_routes + rest_routes:
        app.routes.append(route)

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an A2A agent (SDK version)")
    parser.add_argument("--kind", choices=AGENT_CONFIGS.keys(), required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()

    app = make_sdk_app(args.kind, args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()

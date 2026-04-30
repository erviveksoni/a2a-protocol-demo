"""Agent Executors — the business logic behind each A2A agent.

Each executor implements AgentExecutor.execute() to handle incoming
messages. The SDK handles all the protocol wiring (routes, JSON-RPC,
task storage, etc.).
"""

from a2a_sdk_demo.server.executors.pizza_executor import PizzaExecutor
from a2a_sdk_demo.server.executors.burger_executor import BurgerExecutor
from a2a_sdk_demo.server.executors.catering_executor import CateringExecutor
from a2a_sdk_demo.server.executors.pasta_executor import PastaExecutor

__all__ = ["PizzaExecutor", "BurgerExecutor", "CateringExecutor", "PastaExecutor"]

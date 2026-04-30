"""LLM-Powered Planning — smart delegation via Amazon Bedrock.

Uses the Bedrock Converse API to analyze user requests and decide
which agents to call with what orders. Also summarizes results.

Configuration is via environment variables (or .env file):
  - AWS_REGION:    Required. The AWS region for Bedrock.
  - BEDROCK_MODEL: Required. The model ID.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv

load_dotenv()  # Load .env file if present (for AWS_REGION, BEDROCK_MODEL, etc.)


class BedrockLLM:
    """AWS Bedrock client using the Converse API.

    Configuration is entirely via environment variables (or .env file):
      - AWS_REGION:    Required. The AWS region for Bedrock (e.g. us-east-1).
      - BEDROCK_MODEL: Required. The model ID (e.g. anthropic.claude-3-haiku-20240307-v1:0).
    """

    def __init__(self) -> None:
        import boto3

        region = os.environ.get("AWS_REGION")
        if not region:
            raise RuntimeError(
                "AWS_REGION not set. Please set it in your .env file or environment.\n"
                "  Example: AWS_REGION=us-east-1"
            )

        model = os.environ.get("BEDROCK_MODEL")
        if not model:
            raise RuntimeError(
                "BEDROCK_MODEL not set. Please set it in your .env file or environment.\n"
                "  Example: BEDROCK_MODEL=anthropic.claude-3-haiku-20240307-v1:0"
            )

        self.client = boto3.client("bedrock-runtime", region_name=region)
        self.model_id = model

    def chat(self, system: str, user: str) -> str:
        resp = self.client.converse(
            modelId=self.model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig={"temperature": 0.3, "maxTokens": 1024},
        )
        return resp["output"]["message"]["content"][0]["text"]


def create_llm_client() -> BedrockLLM:
    try:
        return BedrockLLM()
    except Exception as exc:
        raise RuntimeError(
            "\n❌ Could not initialize Amazon Bedrock.\n"
            f"   Error: {exc}\n"
        ) from exc


PLAN_SYSTEM = """\
You are the Lunch Concierge, an AI coordinator that delegates food orders to \
specialized seller agents.

Available seller agents:
{agent_info}

Your job:
1. Analyze the user's lunch request (dietary needs, budget, head-count, preferences).
2. Decide which agent(s) to contact and what specific items to order from each.
3. Output ONLY a JSON array of delegation objects. No other text.

Each object must have:
  "agent_name"  – exact name of the agent (from the list above)
  "skill_id"    – the skill ID to invoke (from the agent's skills list)
  "order_text"  – a clear, specific order instruction for that agent

Pricing (per unit):
  Pizza Seller:  any pizza = $12, ready in 20 min
  Burger Seller: any burger = $9,  ready in 10 min
  Pasta Seller:  any pasta = $11, ready in 15 min
  Catering Planner: ~$10/person (wraps, burgers, pizzas), ready in 60-90 min. \
Best for groups of 10+ people.

Rules:
- Respect dietary requirements (vegetarian → veggie pizza / veggie burger / pasta).
- ALWAYS try to use at least 2-3 different agents for variety. Don't order only from Pizza and Burger — \
include Pasta when ordering for multiple people.
- For vegetarian items, prefer pasta (it's naturally vegetarian).
- For non-vegetarian items, use burger (cheeseburger) or pizza (pepperoni).
- Stay within any stated budget.
- Be specific about item names and quantities.
- For groups of 10+ people, prefer the Catering Planner Agent for bulk ordering.

Example output:
[
  {{"agent_name": "Pizza Seller Agent", "skill_id": "create_pizza_order", "order_text": "Order 2 veggie pizzas"}},
  {{"agent_name": "Burger Seller Agent", "skill_id": "create_burger_order", "order_text": "Order 1 cheeseburger"}},
  {{"agent_name": "Pasta Seller Agent", "skill_id": "create_pasta_order", "order_text": "Order 1 penne pasta"}}
]"""

SUMMARY_SYSTEM = """\
You are the Lunch Concierge. Summarize the completed order for the user.
Be friendly and concise. Mention: items ordered, who they're for (if known), \
total cost, budget status (if a budget was given), and estimated pickup time.
Use emoji sparingly (1-2 max)."""


@dataclass
class DelegationPlan:
    agent_name: str
    skill_id: str
    order_text: str


def build_agent_info(agents: list[dict]) -> str:
    lines: list[str] = []
    for agent in agents:
        skills = agent.get("skills", [])
        skill_desc = "; ".join(
            f"{s.get('name', '?')} – {s.get('description', '')}" for s in skills
        )
        tags = ", ".join(t for s in skills for t in s.get("tags", []))
        lines.append(f"- {agent['name']}\n  Skills: {skill_desc}\n  Tags: {tags}")
    return "\n".join(lines)


def _extract_json_array(text: str) -> list[dict[str, str]]:
    cleaned = text.strip()
    if "```" in cleaned:
        m = re.search(r"```(?:json)?\s*\n?(.*?)```", cleaned, re.DOTALL)
        if m:
            cleaned = m.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\[.*]", text, re.DOTALL)
        if m:
            return json.loads(m.group())
        raise ValueError(f"Could not parse JSON from LLM response:\n{text}")


def plan_delegations(
    llm: BedrockLLM, agents: list[dict], user_request: str
) -> list[DelegationPlan]:
    system = PLAN_SYSTEM.format(agent_info=build_agent_info(agents))
    raw = llm.chat(system, user_request)
    items = _extract_json_array(raw)
    return [DelegationPlan(agent_name=i["agent_name"], skill_id=i.get("skill_id", ""), order_text=i["order_text"]) for i in items]


def summarize_results(
    llm: BedrockLLM,
    user_request: str,
    delegations: list[tuple[str, str, str]],
) -> str:
    details = "\n".join(
        f'- Sent to {name}: "{sent}"\n  Response: {reply}'
        for name, sent, reply in delegations
    )
    user_msg = f'Original request: "{user_request}"\n\nAgent responses:\n{details}'
    return llm.chat(SUMMARY_SYSTEM, user_msg)

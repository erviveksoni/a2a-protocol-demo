"""Shared utilities for agent executors.

Common helper functions used across all food-ordering executors.
"""

from __future__ import annotations

import re

from a2a.types.a2a_pb2 import Message


def extract_text(message: Message) -> str:
    """Extract all text from an A2A Message's parts.

    Args:
        message: An A2A protobuf Message with one or more Parts.

    Returns:
        Combined text from all text-bearing parts, stripped of whitespace.
    """
    parts = []
    for part in message.parts:
        if part.text:
            parts.append(part.text)
    return " ".join(parts).strip()


def choose_quantity(text: str) -> int:
    """Parse a quantity from natural language order text.

    Supports both word numbers ("two pizzas") and digit numbers ("3 burgers").
    Defaults to 1 if no quantity is found.

    Args:
        text: The user's order text.

    Returns:
        An integer quantity (1-9).
    """
    lower = text.lower()
    number_words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
    for word, value in number_words.items():
        if re.search(rf"\b{word}\b", lower):
            return value
    match = re.search(r"\b([1-9])\b", lower)
    return int(match.group(1)) if match else 1

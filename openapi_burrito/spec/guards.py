"""
Shape guards for untrusted documents.

A spec that passed validation can still put a list where we expect an object
or a number where we expect text (``"components": null`` is a classic).
Every structural read in ``spec/`` goes through these so a malformed node
degrades to "nothing there" instead of an AttributeError.
"""

from typing import Any


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def as_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""

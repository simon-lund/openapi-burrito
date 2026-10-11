"""
Internal ``$ref`` resolution.

Specs are loaded with external (file/HTTP) refs resolved but internal
``#/...`` refs left intact. Keeping ref identity means "which model is this?"
is answered by reading the ref target instead of content-hashing schema
copies, and recursive schemas (e.g. tree nodes) work naturally.
"""

import logging
from typing import Any
from urllib.parse import unquote

logger = logging.getLogger(__name__)

SCHEMA_REF_PREFIX = "#/components/schemas/"


def _unescape_pointer_segment(segment: str) -> str:
    """Decodes a JSON pointer segment per RFC 6901 (~1 -> /, ~0 -> ~)."""
    return unquote(segment).replace("~1", "/").replace("~0", "~")


class RefResolver:
    """Resolves internal ``$ref`` pointers against the spec document."""

    def __init__(self, spec: Any) -> None:
        self._spec = spec

    def schema_name(self, ref: Any) -> str | None:
        """
        The raw ``components/schemas`` key ``ref`` points at, or None if it
        points anywhere else (another location, or a nested pointer such as
        ``.../Pet/properties/id``, which is not a named model).
        """
        if not isinstance(ref, str) or not ref.startswith(SCHEMA_REF_PREFIX):
            return None
        remainder = ref.removeprefix(SCHEMA_REF_PREFIX)
        if "/" in remainder:
            return None
        return _unescape_pointer_segment(remainder)

    def deref(self, node: Any) -> Any:
        """
        Follows a chain of internal ``$ref`` pointers to the actual object.

        Non-dict nodes and nodes without ``$ref`` are returned as-is. Broken,
        external, or circular refs resolve to ``{}`` (treated as "Any"
        downstream) with a warning, so one bad ref never aborts generation.
        """
        seen: set[str] = set()
        while isinstance(node, dict) and "$ref" in node:
            ref = node["$ref"]
            if not isinstance(ref, str) or not ref.startswith("#/"):
                logger.warning("Cannot resolve non-internal $ref %r", ref)
                return {}
            if ref in seen:
                logger.warning("Circular $ref chain involving %r", ref)
                return {}
            seen.add(ref)

            target: Any = self._spec
            for segment in ref[2:].split("/"):
                key = _unescape_pointer_segment(segment)
                try:
                    target = (
                        target[int(key)] if isinstance(target, list) else target[key]
                    )
                except (KeyError, IndexError, ValueError, TypeError):
                    logger.warning("Unresolvable $ref %r (missing %r)", ref, key)
                    return {}
            node = target

        return node

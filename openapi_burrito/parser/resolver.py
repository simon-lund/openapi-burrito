"""Internal $ref resolution for partially-resolved OpenAPI specs.

The generator loads specs with external (file/HTTP) refs resolved but internal
``#/...`` refs left intact. Keeping ref identity means "which model is this?"
is answered by reading the ref target instead of content-hashing schema copies,
and recursive schemas (e.g. tree nodes) work naturally.
"""

import logging
from typing import Any
from urllib.parse import unquote

from .sanitize import sanitize

logger = logging.getLogger(__name__)

SCHEMA_REF_PREFIX = "#/components/schemas/"


def _unescape_pointer_segment(segment: str) -> str:
    """Decodes a JSON pointer segment per RFC 6901 (~1 -> /, ~0 -> ~)."""
    return unquote(segment).replace("~1", "/").replace("~0", "~")


class RefResolver:
    """Resolves internal ``$ref`` pointers against the spec document."""

    def __init__(self, spec: dict[str, Any]) -> None:
        """
        :param spec: The OpenAPI spec with internal $refs left unresolved.
        """
        self._spec = spec

    def schema_name(self, ref: Any) -> str | None:
        """
        Returns the sanitized model name if ``ref`` points directly at a named
        schema in ``components/schemas``, else None.
        """
        if not isinstance(ref, str) or not ref.startswith(SCHEMA_REF_PREFIX):
            return None

        remainder = ref.removeprefix(SCHEMA_REF_PREFIX)
        # A nested pointer (e.g. .../Pet/properties/id) is not a named model
        if "/" in remainder:
            return None

        return sanitize(_unescape_pointer_segment(remainder), mode="id")

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

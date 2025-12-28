"""Schema lookup table for resolving $ref schemas to model names."""

import hashlib
import json
import logging
from typing import Any

from ..utils import dig
from .sanitize import sanitize

logger = logging.getLogger(__name__)


def _schema_hash(schema: dict[str, Any]) -> str:
    """Creates a stable MD5 hash of a schema dict for lookup purposes."""
    serialized = json.dumps(schema, sort_keys=True, default=str)
    return hashlib.md5(serialized.encode()).hexdigest()


class SchemaLookup:
    """
    A lookup table for resolving schema dicts to their model names.

    When prance resolves $refs, it creates copies of schema objects.
    This class uses content hashing to match any copy of a schema
    back to its original name in components/schemas.
    """

    def __init__(self, resolved_spec: dict[str, Any]):
        """
        Initializes the lookup table from the resolved OpenAPI spec.

        :param resolved_spec: The OpenAPI spec where $refs have been replaced.
        """
        schemas = dig(resolved_spec, ("components", "schemas"), default={})
        self._lookup: dict[str, str] = {
            _schema_hash(schema): sanitize(name, mode="id")
            for name, schema in schemas.items()
        }
        logger.debug("Built schema lookup with %d entries", len(self._lookup))

    def get(self, schema: dict[str, Any]) -> str | None:
        """
        Looks up a schema dict and returns its model name if found.

        :param schema: A schema dict (possibly a resolved $ref copy).
        :return: The sanitized model name, or None if not in components/schemas.
        """
        return self._lookup.get(_schema_hash(schema))

    def __contains__(self, schema: dict[str, Any]) -> bool:
        """Checks if a schema exists in the lookup table."""
        return _schema_hash(schema) in self._lookup

    def __len__(self) -> int:
        """Returns the number of schemas in the lookup table."""
        return len(self._lookup)

"""Schema parser for OpenAPI specifications."""

import logging
from typing import Any

from ..utils import dig
from .lookup import SchemaLookup
from .models import ParsedModel, ParsedProperty
from .sanitize import safe_bool, sanitize
from .types import TypeTranslator

logger = logging.getLogger(__name__)


def flatten_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """
    Recursively merges 'allOf' structures into a single flat properties' dictionary.

    This handles nested inheritance (e.g., Admin -> User -> BaseModel) by
    traversing the tree and aggregating all properties and required fields into
    a single schema representation.

    :param schema: The schema dictionary to flatten.
    :return: A new dictionary containing the merged properties and required fields.
    """
    if not schema.get("allOf"):
        return schema

    flat_properties: dict[str, Any] = {}
    flat_required = set()

    # Recursively process each subschema in the inheritance chain
    for subschema in schema["allOf"]:
        resolved_sub = flatten_schema(subschema)
        flat_properties |= resolved_sub.get("properties", {})
        flat_required |= set(resolved_sub.get("required", []))

    # Own properties override inherited ones
    flat_properties |= schema.get("properties", {})
    flat_required |= set(schema.get("required", []))

    # Build the flattened schema
    flattened_schema = schema.copy()
    flattened_schema["properties"] = flat_properties
    flattened_schema["required"] = list(flat_required)

    # Remove allOf to prevent downstream double-processing
    flattened_schema.pop("allOf", None)
    return flattened_schema


class SchemaParser:
    """Parses OpenAPI definitions into a structured list of model dictionaries."""

    def __init__(self, resolved_spec: dict[str, Any]) -> None:
        """
        Initializes the SchemaParser with a resolved OpenAPI specification.

        :param resolved_spec: The resolved OpenAPI specification dictionary.
        """
        self.resolved_spec = resolved_spec
        self.schema_lookup = SchemaLookup(resolved_spec)
        self.type_translator = TypeTranslator(self.schema_lookup)

    def __call__(self) -> list[ParsedModel]:
        """Callable alias for parse method."""
        return self.parse()

    def parse(self) -> list[ParsedModel]:
        """
        Parses all schemas in the OpenAPI specification.

        :return: A list of dictionaries, each representing a model with its properties.
        """
        models = []
        schemas = dig(self.resolved_spec, ("components", "schemas"), default={})

        for name, schema in schemas.items():
            logger.debug("Parsing schema %s", name)

            # Deep flatten the schema's inheritance structure (if any)
            flat = flatten_schema(schema)
            properties = flat.get("properties", {})
            required_fields = set(flat.get("required", []))

            model_props = [
                self._parse_property(p_name, p_schema, p_name in required_fields)
                for p_name, p_schema in properties.items()
            ]

            models.append(
                ParsedModel(
                    name=sanitize(name, mode="id"),
                    properties=model_props,
                    doc=sanitize(schema.get("description", ""), mode="doc"),
                )
            )

        return models

    def _parse_property(
        self, name: str, schema: dict[str, Any], required: bool
    ) -> ParsedProperty:
        """Parses a single property schema into a ParsedProperty."""
        py_type = self.type_translator(schema)
        if not required:
            py_type = f"NotRequired[{py_type}]"

        # Handle default value (already converted by resolver: null->None, etc.)
        # If "default" key exists, use repr() for template rendering; else None
        default = repr(schema["default"]) if "default" in schema else None

        return ParsedProperty(
            name=sanitize(name, mode="id"),
            type=py_type,
            required=required,
            doc=sanitize(schema.get("description", ""), mode="doc"),
            read_only=safe_bool(schema, "readOnly"),
            write_only=safe_bool(schema, "writeOnly"),
            default=default,
        )

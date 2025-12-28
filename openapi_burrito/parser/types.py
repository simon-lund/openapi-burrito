"""Translator module for OpenAPI schemas to Python type hints."""

import logging
from dataclasses import dataclass, field
from typing import Any

from .lookup import SchemaLookup
from .sanitize import sanitize

logger = logging.getLogger(__name__)


@dataclass
class TypeNode:
    """Represents a Python type hint as a structured node for manipulation."""

    name: str
    args: list["TypeNode"] = field(default_factory=list)
    is_nullable: bool = False

    NON_NULLABLE_TYPES = {"Any", "None"}

    def __hash__(self) -> int:
        """Hash based on rendered representation for use in sets."""
        return hash(self.render())

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TypeNode):
            return NotImplemented
        return self.render() == other.render()

    def render(self) -> str:
        if self.name == "Union":
            rendered_parts = {arg.render() for arg in self.args}
            rendered_parts.discard("None")
            parts = sorted(list(rendered_parts))
            base = " | ".join(parts)
        elif self.args:
            arg_str = ", ".join(arg.render() for arg in self.args)
            base = f"{self.name}[{arg_str}]"
        else:
            base = self.name

        # Nullability handling
        is_non_nullable = self.name in self.NON_NULLABLE_TYPES
        is_union_with_none = self.name == "Union" and any(
            arg.render() == "None" for arg in self.args
        )

        if self.is_nullable and not is_non_nullable and not is_union_with_none:
            return f"{base} | None"

        return base


class TypeTranslator:
    """Translates OpenAPI schemas into Python type hint strings."""

    primitive_type_map = {
        "integer": "int",
        "boolean": "bool",
        "number": "float",
        "null": "None",
    }

    def __init__(self, schema_lookup: SchemaLookup):
        """
        Initializes the TypeTranslator with a schema lookup table.

        :param schema_lookup: A SchemaLookup instance for looking up model names
            by schema.
        """
        self.schema_lookup = schema_lookup

    def __call__(self, schema: Any) -> str:
        """Convenience method to get the rendered string directly."""
        return self.translate(schema).render()

    def translate(self, schema: Any) -> TypeNode:
        """The core translation logic. Returns a TypeNode for rich manipulation."""
        # Boolean schemas (JSON Schema draft 2020-12 / OpenAPI 3.1)
        if schema is True or schema is None or schema == {}:
            return TypeNode("Any")  # No constraints = any value valid
        if schema is False:
            return TypeNode("Never")  # No value valid

        # Check if schema is a resolved model reference
        if model_name := self.schema_lookup.get(schema):
            return TypeNode(model_name)

        schema_type = schema.get("type")

        # Infer type from structure if not explicitly set
        if not schema_type:
            if "properties" in schema or "additionalProperties" in schema:
                schema_type = "object"
            elif "items" in schema:
                schema_type = "array"

        # Handle polymorphic/composition types first
        if "enum" in schema:
            node = self._handle_enum(schema)
        elif any(k in schema for k in ("oneOf", "anyOf")):
            node = self._handle_poly(schema)
        elif "allOf" in schema:
            # allOf with single item is just that type (common $ref wrapper pattern)
            all_of = schema["allOf"]
            if len(all_of) == 1:
                node = self.translate(all_of[0])
            else:
                # Multi-item allOf (intersection) not supported, default to Any
                # TODO: implement this
                node = TypeNode("Any")
        elif isinstance(schema_type, list):
            node = self._handle_multi(schema)
        else:
            handler = getattr(self, f"_handle_{schema_type}", self._handle_default)
            node = handler(schema)

        node.is_nullable = schema.get("nullable", False)
        return node

    def _handle_enum(self, schema: dict[str, Any]) -> TypeNode:
        literals = [
            f'"{sanitize(v, mode="str")}"' if isinstance(v, str) else str(v)
            for v in schema["enum"]
        ]
        return TypeNode("Literal", args=[TypeNode(lit) for lit in literals])

    def _handle_poly(self, schema: dict[str, Any]) -> TypeNode:
        """
        Handles OpenAPI polymorphic types (oneOf/anyOf).
        """
        # TODO: anyOf ist not properly handled yet
        # TODO: Consider discriminators for more accurate typing
        # TODO: both can be present; need to handle that case

        if "oneOf" in schema:
            logger.debug("Handling oneOf schema for polymorphism.")
            nodes = {self.translate(s) for s in schema["oneOf"]}
            return TypeNode("Union", args=list(nodes))
        elif "anyOf" in schema:
            logger.warning("anyOf handling is not supported yet, defaulting to Any.")
            return TypeNode("Any")
        else:
            logger.error("Polymorphic schema without oneOf or anyOf keys.")
            return TypeNode("Any")

    def _handle_multi(self, schema: dict[str, Any]) -> TypeNode:
        """
        Handles OpenAPI 3.1 multi-type arrays (e.g., type: ["string", "null"]).

        Resolves each type in the list and combines them into a union.
        """
        nodes = set()

        # For each type in the list, create a sub-schema and translate it
        # Note: We set nullable=False in children to prevent redundant 'None' hints
        # (e.g., 'str | None | None') when 'null' is already in the type list.
        for t in schema["type"]:
            sub_schema = {**schema, "type": t, "nullable": False}
            nodes.add(self.translate(sub_schema))

        return TypeNode("Union", args=list(nodes))

    def _handle_array(self, schema: dict[str, Any]) -> TypeNode:
        items = schema.get("items")
        if items:
            return TypeNode("list", args=[self.translate(items)])
        logger.debug("Array schema missing items key, defaulting to list[Any]")
        return TypeNode("list", args=[TypeNode("Any")])

    def _handle_object(self, schema: dict[str, Any]) -> TypeNode:
        """
        Handles object schemas not resolved via schema_lookup.

        For typed dicts (additionalProperties with schema), returns dict[str, T].
        For everything else (inline objects, generic objects), returns dict[str, Any].
        """
        add_props = schema.get("additionalProperties")

        # Typed dict: {"additionalProperties": {"type": "string"}} -> dict[str, str]
        value_type = self.translate(add_props if isinstance(add_props, dict) else {})

        logger.warning(
            "Inline object schema detected. Defaulting to dict[str, %s]. ",
            value_type.render(),
        )
        return TypeNode("dict", args=[TypeNode("str"), value_type])

    def _handle_string(self, schema: dict[str, Any]) -> TypeNode:
        is_binary = schema.get("format") == "binary"
        return TypeNode("bytes" if is_binary else "str")

    def _handle_default(self, schema: dict[str, Any]) -> TypeNode:
        schema_type = schema.get("type")

        if isinstance(schema_type, str):
            primitive_type = self.primitive_type_map.get(schema_type)
            if primitive_type:
                return TypeNode(primitive_type)

        # Log and default to Any
        if not isinstance(schema_type, str):
            logger.warning(
                "Schema type is not a string: %s, defaulting to Any",
                schema_type,
            )
        else:
            logger.warning(
                "Unknown schema type %s, defaulting to Any",
                "(supported types: %s)",
                schema_type,
                ", ".join(self.primitive_type_map.keys()),
            )

        return TypeNode("Any")

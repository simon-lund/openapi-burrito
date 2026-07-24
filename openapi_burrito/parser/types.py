"""Translator module for OpenAPI schemas to Python type hints."""

import logging
from dataclasses import dataclass, field
from typing import Any

from .resolver import RefResolver
from .sanitize import sanitize

logger = logging.getLogger(__name__)


def _as_list(value: Any) -> list[Any]:
    """Malformed-spec guard: anything that should be a list but is not."""
    return value if isinstance(value, list) else []


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
        nullable = self.is_nullable and self.name not in self.NON_NULLABLE_TYPES

        if self.name == "Union":
            parts = {arg.render() for arg in self.args}
            # 'None' is re-appended at the end so it always renders last
            nullable = nullable or "None" in parts
            parts.discard("None")
            if not parts:
                return "None" if nullable else "Any"
            base = " | ".join(sorted(parts))
        elif self.args:
            arg_str = ", ".join(arg.render() for arg in self.args)
            base = f"{self.name}[{arg_str}]"
        else:
            base = self.name

        return f"{base} | None" if nullable else base


class TypeTranslator:
    """Translates OpenAPI schemas into Python type hint strings."""

    primitive_type_map = {
        "integer": "int",
        "boolean": "bool",
        "number": "float",
        "string": "str",
        "null": "None",
    }

    format_type_map: dict[tuple[str, str | None], str] = {
        ("string", "binary"): "bytes",
    }
    """
    Overrides for (type, format) pairs. Extension point: add e.g.
    ("string", "date-time") -> "datetime.datetime" once value transformation
    is supported.
    """

    def __init__(self, resolver: RefResolver):
        """
        :param resolver: Resolver used to map $refs to model names and to
            dereference refs that don't point at named schemas.
        """
        self.resolver = resolver

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

        if not isinstance(schema, dict):
            logger.warning("Schema is not an object: %r, defaulting to Any", schema)
            return TypeNode("Any")

        node = self._translate_inner(schema)
        # 'nullable' (OpenAPI 3.0) combines with nullability found inside
        # (e.g. an allOf-wrapped $ref with a nullable sibling)
        node.is_nullable = node.is_nullable or bool(schema.get("nullable", False))
        return node

    def _translate_inner(self, schema: dict[str, Any]) -> TypeNode:
        # Named model reference ($ref identity is preserved by the loader)
        if "$ref" in schema:
            if model_name := self.resolver.schema_name(schema["$ref"]):
                return TypeNode(model_name)
            # Ref to a non-schema location (or nested pointer): inline it
            return self.translate(self.resolver.deref(schema))

        if "enum" in schema:
            return self._handle_enum(schema)

        if "oneOf" in schema or "anyOf" in schema:
            return self._handle_union(schema)

        if "allOf" in schema:
            # allOf with single item is just that type (common $ref wrapper pattern)
            all_of = _as_list(schema["allOf"])
            if len(all_of) == 1:
                return self.translate(all_of[0])
            # Multi-item allOf (intersection) not supported, default to Any
            # TODO: merge properties into a synthetic model
            return TypeNode("Any")

        schema_type = schema.get("type")

        # Infer type from structure if not explicitly set
        if not schema_type:
            if "properties" in schema or "additionalProperties" in schema:
                schema_type = "object"
            elif "items" in schema:
                schema_type = "array"

        # OpenAPI 3.1 multi-type arrays (e.g. type: ["string", "null"])
        if isinstance(schema_type, list):
            return self._handle_multi(schema)

        if isinstance(schema_type, str):
            fmt = schema.get("format")
            if override := self.format_type_map.get(
                (schema_type, fmt if isinstance(fmt, str) else None)
            ):
                return TypeNode(override)
            if schema_type == "array":
                return self._handle_array(schema)
            if schema_type == "object":
                return self._handle_object(schema)
            if primitive := self.primitive_type_map.get(schema_type):
                return TypeNode(primitive)

        logger.warning(
            "Unknown schema type %r, defaulting to Any (supported types: %s)",
            schema_type,
            ", ".join(self.primitive_type_map),
        )
        return TypeNode("Any")

    def _handle_enum(self, schema: dict[str, Any]) -> TypeNode:
        values = _as_list(schema["enum"])
        if not values:
            logger.warning("Malformed enum %r, defaulting to Any", schema["enum"])
            return TypeNode("Any")
        literals = [
            f'"{sanitize(v, mode="str")}"' if isinstance(v, str) else str(v)
            for v in values
        ]
        return TypeNode("Literal", args=[TypeNode(lit) for lit in literals])

    def _handle_union(self, schema: dict[str, Any]) -> TypeNode:
        """
        Handles oneOf/anyOf composition as a union of the subschemas.

        anyOf strictly means "valid against at least one" — a union is the
        closest Python approximation for both.
        """
        # TODO: Consider discriminators for more accurate typing
        subschemas = _as_list(schema.get("oneOf")) + _as_list(schema.get("anyOf"))
        nodes = {self.translate(s) for s in subschemas}
        return TypeNode("Union", args=list(nodes))

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
        Handles inline object schemas (no $ref to a named model).

        For typed dicts (additionalProperties with schema), returns dict[str, T].
        For everything else (inline objects, generic objects), returns dict[str, Any].
        """
        add_props = schema.get("additionalProperties")

        # Typed dict: {"additionalProperties": {"type": "string"}} -> dict[str, str]
        value_type = self.translate(add_props if isinstance(add_props, dict) else {})

        logger.debug(
            "Inline object schema detected, defaulting to dict[str, %s]",
            value_type.render(),
        )
        return TypeNode("dict", args=[TypeNode("str"), value_type])

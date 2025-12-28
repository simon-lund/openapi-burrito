import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TypeNode:
    name: str
    args: list['TypeNode'] = field(default_factory=list)
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
        if self.name == 'Union':
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
        is_union_with_none = self.name == "Union" and any(arg.render() == "None" for arg in self.args)

        if self.is_nullable and not is_non_nullable and not is_union_with_none:
            return f"{base} | None"

        return base


class TypeTranslator:
    """Translates OpenAPI schemas into Python type hint strings."""

    primitive_type_map = {
        "integer": "int",
        "boolean": "bool",
        "number": "float",
        "null": "None"
    }

    def __init__(self, schema_lookup: dict[int, str]):
        """
        Initializes the TypeTranslator with a schema lookup table.

        :param schema_lookup: A dictionary mapping memory IDs to model names (see schema.py:build_schema_lookup).
        """
        self.schema_lookup = schema_lookup

    def __call__(self, schema: dict[str, Any]) -> str:
        """Convenience method to get the rendered string directly."""
        return self.translate(schema).render()

    def translate(self, schema: dict[str, Any]) -> TypeNode:
        """The core translation logic. Returns a TypeNode for rich manipulation."""
        if not schema:
            return TypeNode("Any")

        # Check if schema is a resolved model reference (i.e., if resolver replaced $ref with actual schema)
        # in this case we backtrack to the model name via the schema_lookup
        if id(schema) in self.schema_lookup:
            return TypeNode(self.schema_lookup[id(schema)])

        schema_type = schema.get("type")

        if "enum" in schema:
            node = self._handle_enum(schema)
        elif any(k in schema for k in ("oneOf", "anyOf")):
            node = self._handle_poly(schema)
        elif isinstance(schema_type, list):
            node = self._handle_multi(schema)
        else:
            handler = getattr(self, f"_handle_{schema_type}", self._handle_default)
            node = handler(schema)

        node.is_nullable = schema.get("nullable", False)
        return node

    def _handle_enum(self, schema: dict[str, Any]) -> TypeNode:
        literals = [f'"{v}"' if isinstance(v, str) else str(v) for v in schema["enum"]]
        return TypeNode("Literal", args=[TypeNode(l) for l in literals])

    def _handle_poly(self, schema: dict[str, Any]) -> TypeNode:
        """
        Handles OpenAPI polymorphic types (oneOf/anyOf).
        """
        # TODO: anyOf ist not properly handled yet
        # TODO: Consider discriminators for more accurate typing
        # TODO: both can be present; need to handle that case

        key = "oneOf" if "oneOf" in schema else "anyOf"
        nodes = {self.translate(s) for s in schema[key]}
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
        logger.warning("Array schema missing 'items' key. Falling back to list[Any].")
        return TypeNode("list", args=[TypeNode("Any")])

    def _handle_object(self, schema: dict[str, Any]) -> TypeNode:
        add_props = schema.get("additionalProperties")  # Could be dict, bool, or None

        if isinstance(add_props, dict):
            return TypeNode("dict", args=[TypeNode("str"), self.translate(add_props)])

        logger.warning("Generic object detected. Defaulting to dict[str, Any].")
        return TypeNode("dict", args=[TypeNode("str"), TypeNode("Any")])

    def _handle_string(self, schema: dict[str, Any]) -> TypeNode:
        is_binary = schema.get("format") == "binary"
        return TypeNode("bytes" if is_binary else "str")

    def _handle_default(self, schema: dict[str, Any]) -> TypeNode:
        schema_type = schema.get("type")
        if primitive_type := self.primitive_type_map.get(schema_type):
            return TypeNode(primitive_type)

        # If the type is completely missing or unknown to us
        logger.warning(f"Unknown or missing type '{schema_type}'. Falling back to Any.")
        return TypeNode("Any")

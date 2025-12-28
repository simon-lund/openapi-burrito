import logging
from typing import Any

from .types import TypeTranslator
from ..utils import dig

logger = logging.getLogger(__name__)


def build_schema_lookup(resolved_spec: dict[str, Any]) -> dict[int, str]:
    """
    Builds a name-lookup table based on the physical memory address of schema objects.

    When the ResolvingParser replaces a $ref with its target, it doesn't just copy
    the data; it inserts a reference to the exact same dictionary object found in
    the 'components/schemas' section.

    By mapping the unique memory ID (id()) of these original dictionaries to
    their names, we can identify a Model even when we encounter it deeply nested
    inside other models or operations, regardless of its original $ref string.

    :param resolved_spec: The OpenAPI spec where $refs have been replaced by object references.
    :return: A dictionary where {memory_id: "ModelName"}.
    """
    schemas = dig(resolved_spec, ("components", "schemas"), default={})
    return {id(schema): name for name, schema in schemas.items()}


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

    flat_properties = {}
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
        self.schema_lookup = build_schema_lookup(resolved_spec)
        self.type_translator = TypeTranslator(self.schema_lookup)

    def __call__(self):
        """Callable alias for parse method."""
        return self.parse()

    def parse(self) -> list[dict[str, Any]]:
        """
        Parses all schemas in the OpenAPI specification.

        :return: A list of dictionaries, each representing a model with its properties.
        """
        models = []
        schemas = dig(self.resolved_spec, ("components", "schemas"), default={})

        for name, schema in schemas.items():
            logger.info("Parsing schema: %s", name, extra={"schema": name})

            # Deep flatten the schema's inheritance structure (if any)
            flat = flatten_schema(schema)
            properties = flat.get("properties", {})
            required_fields = set(flat.get("required", []))

            model_props = []
            for p_name, p_schema in properties.items():
                py_type = self.type_translator(p_schema)
                if p_name not in required_fields:
                    py_type = f"NotRequired[{py_type}]"

                p_default = p_schema.get("default")

                model_props.append({
                    "name": p_name,
                    "type": py_type,
                    "doc": p_schema.get("description", ""),
                    "read_only": p_schema.get("readOnly", False),
                    "write_only": p_schema.get("writeOnly", False),
                    "default": repr(p_default) if p_default is not None else None
                })

            models.append({
                "name": name,
                "properties": model_props,
                "doc": schema.get("description", "")
            })

        return models
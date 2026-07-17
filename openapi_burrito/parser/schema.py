"""Schema parser for OpenAPI specifications."""

import keyword
import logging
from typing import Any

from ..utils import dig
from .models import ParsedModel, ParsedProperty
from .resolver import RefResolver
from .sanitize import safe_bool, sanitize
from .types import TypeTranslator

logger = logging.getLogger(__name__)


def flatten_schema(
    schema: dict[str, Any],
    resolver: RefResolver,
    _seen: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """
    Recursively merges 'allOf' structures into a single flat properties' dictionary.

    This handles nested inheritance (e.g., Admin -> User -> BaseModel) by
    traversing the tree and aggregating all properties and required fields into
    a single schema representation.

    :param schema: The schema (or $ref to one) to flatten.
    :param resolver: Resolver for dereferencing allOf items.
    :param _seen: $refs already visited on this branch (guards allOf cycles).
    :return: A new dictionary containing the merged properties and required fields.
    """
    schema = resolver.deref(schema)
    if not schema.get("allOf"):
        return schema

    flat_properties: dict[str, Any] = {}
    flat_required = set()

    # Recursively process each subschema in the inheritance chain
    for subschema in schema["allOf"]:
        if isinstance(subschema, dict) and (ref := subschema.get("$ref")):
            if ref in _seen:
                logger.warning("Circular allOf inheritance via %r, skipping", ref)
                continue
            _seen |= {ref}

        resolved_sub = flatten_schema(subschema, resolver, _seen)
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


def _is_plain_key(name: str) -> bool:
    """Whether a wire key can be used verbatim in class-syntax TypedDict."""
    return name.isidentifier() and not keyword.iskeyword(name)


class SchemaParser:
    """Parses OpenAPI definitions into a structured list of model dictionaries."""

    def __init__(self, spec: dict[str, Any]) -> None:
        """
        Initializes the SchemaParser.

        :param spec: The OpenAPI spec with internal $refs left unresolved.
        """
        self.spec = spec
        self.resolver = RefResolver(spec)
        self.type_translator = TypeTranslator(self.resolver)

    def parse(self) -> list[ParsedModel]:
        """
        Parses all schemas in the OpenAPI specification.

        :return: A list of ParsedModel entries, one per named schema.
        """
        models = []
        schemas = dig(self.spec, ("components", "schemas"), default={})

        for name, schema in schemas.items():
            logger.debug("Parsing schema %s", name)

            # Deep flatten the schema's inheritance structure (if any)
            flat = flatten_schema(schema, self.resolver)
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
                    # Keys must match the wire format; if any key can't be a
                    # class attribute, the template falls back to functional
                    # TypedDict syntax for the whole model.
                    functional=not all(_is_plain_key(p.name) for p in model_props),
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

        # Metadata (description, default, ...) lives on the resolved schema
        # when the property is a $ref
        resolved = self.resolver.deref(schema)
        default = repr(resolved["default"]) if "default" in resolved else None

        return ParsedProperty(
            # Wire key kept verbatim: TypedDict keys must match the JSON.
            # Rendering is injection-safe — plain identifiers go through class
            # syntax, everything else is JSON-escaped in functional syntax.
            name=name,
            type=py_type,
            required=required,
            doc=sanitize(resolved.get("description", ""), mode="doc"),
            read_only=safe_bool(resolved, "readOnly"),
            write_only=safe_bool(resolved, "writeOnly"),
            default=default,
        )

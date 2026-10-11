"""``components/schemas`` → models."""

import logging
from collections.abc import Mapping
from typing import Any

from .. import ir
from . import naming
from .guards import as_dict, as_list, as_text
from .resolver import RefResolver
from .types import type_expr

logger = logging.getLogger(__name__)


def models(spec: Mapping[str, Any], resolver: RefResolver) -> tuple[ir.Model, ...]:
    """One model per named schema, in spec order."""
    schemas = as_dict(as_dict(spec.get("components")).get("schemas"))
    result = []
    for raw_name, schema in schemas.items():
        logger.debug("Parsing schema %s", raw_name)
        flat = flatten(schema, resolver)
        required = {r for r in as_list(flat.get("required")) if isinstance(r, str)}
        fields = tuple(
            _field(str(name), prop, name in required, resolver)
            for name, prop in as_dict(flat.get("properties")).items()
        )
        result.append(
            ir.Model(
                name=naming.model_name(str(raw_name)),
                fields=fields,
                doc=as_text(flat.get("description")),
            )
        )
    return tuple(result)


def flatten(
    schema: Any, resolver: RefResolver, _seen: frozenset[str] = frozenset()
) -> dict[str, Any]:
    """
    Merges an ``allOf`` chain (e.g. Admin → User → BaseModel) into one flat
    schema with all properties and required fields. Own properties override
    inherited ones.

    :param _seen: $refs already visited on this branch (guards allOf cycles).
    """
    node = as_dict(resolver.deref(schema))
    if not node.get("allOf"):
        return node

    properties: dict[str, Any] = {}
    required: set[Any] = set()
    for sub in as_list(node["allOf"]):
        if isinstance(sub, dict) and (ref := sub.get("$ref")):
            if ref in _seen:
                logger.warning("Circular allOf inheritance via %r, skipping", ref)
                continue
            _seen |= {ref}
        flat_sub = flatten(sub, resolver, _seen)
        properties |= as_dict(flat_sub.get("properties"))
        required |= {r for r in as_list(flat_sub.get("required")) if isinstance(r, str)}

    properties |= as_dict(node.get("properties"))
    required |= {r for r in as_list(node.get("required")) if isinstance(r, str)}

    flattened = {k: v for k, v in node.items() if k != "allOf"}
    flattened["properties"] = properties
    flattened["required"] = sorted(required)
    return flattened


def _field(name: str, schema: Any, required: bool, resolver: RefResolver) -> ir.Field:
    # Metadata (description, default, ...) lives on the resolved schema when
    # the property is a $ref
    resolved = as_dict(resolver.deref(schema))
    return ir.Field(
        name=name,
        type=type_expr(schema, resolver),
        required=required,
        doc=as_text(resolved.get("description")),
        default=ir.Default(resolved["default"]) if "default" in resolved else None,
        read_only=bool(resolved.get("readOnly", False)),
        write_only=bool(resolved.get("writeOnly", False)),
    )

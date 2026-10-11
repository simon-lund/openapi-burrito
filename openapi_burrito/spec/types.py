"""JSON Schema → type expression."""

import logging
from typing import Any

from .. import ir
from . import naming
from .guards import as_list
from .resolver import RefResolver

logger = logging.getLogger(__name__)

PRIMITIVES: dict[str, ir.Primitive] = {
    "string": ir.STRING,
    "integer": ir.INTEGER,
    "number": ir.NUMBER,
    "boolean": ir.BOOLEAN,
    "null": ir.NULL,
}

FORMATS: dict[tuple[str, str | None], ir.TypeExpr] = {
    ("string", "binary"): ir.BINARY,
}
"""
Overrides for (type, format) pairs. Extension point: add e.g.
("string", "date-time") once value transformation is supported.
"""


def type_expr(schema: Any, resolver: RefResolver) -> ir.TypeExpr:
    """
    The type of values matching ``schema``.

    Never raises on malformed input: anything unrecognized degrades to
    ``ANY`` with a warning, so one odd schema never aborts generation.
    """
    # Boolean schemas (JSON Schema draft 2020-12 / OpenAPI 3.1)
    if schema is True or schema is None or schema == {}:
        return ir.ANY
    if schema is False:
        return ir.NEVER
    if not isinstance(schema, dict):
        logger.warning("Schema is not an object: %r, defaulting to Any", schema)
        return ir.ANY

    expr = _type_expr(schema, resolver)
    if schema.get("nullable"):  # OpenAPI 3.0 spelling
        expr = ir.union(expr, ir.NULL)
    return expr


def _type_expr(schema: dict[str, Any], resolver: RefResolver) -> ir.TypeExpr:
    if "$ref" in schema:
        if (name := resolver.schema_name(schema["$ref"])) is not None:
            return ir.Ref(naming.model_name(name))
        # Ref to a non-schema location or a nested pointer: inline it
        return type_expr(resolver.deref(schema), resolver)

    if "enum" in schema:
        return _enum(schema["enum"])

    if "oneOf" in schema or "anyOf" in schema:
        # anyOf strictly means "valid against at least one"; a union is the
        # closest Python approximation for both.
        members = as_list(schema.get("oneOf")) + as_list(schema.get("anyOf"))
        return ir.union(*(type_expr(m, resolver) for m in members))

    if "allOf" in schema:
        all_of = as_list(schema["allOf"])
        if len(all_of) == 1:  # the common $ref wrapper pattern
            return type_expr(all_of[0], resolver)
        # TODO: intersection → synthetic model
        return ir.ANY

    kind = schema.get("type")
    if not kind:  # infer from structure
        if "properties" in schema or "additionalProperties" in schema:
            kind = "object"
        elif "items" in schema:
            kind = "array"

    if isinstance(kind, list):  # OpenAPI 3.1: type: ["string", "null"]
        return ir.union(*(type_expr({**schema, "type": t}, resolver) for t in kind))

    if isinstance(kind, str):
        fmt = schema.get("format")
        if override := FORMATS.get((kind, fmt if isinstance(fmt, str) else None)):
            return override
        if kind == "array":
            return ir.Array(type_expr(schema.get("items"), resolver))
        if kind == "object":
            extra = schema.get("additionalProperties")
            return ir.Map(type_expr(extra if isinstance(extra, dict) else {}, resolver))
        if primitive := PRIMITIVES.get(kind):
            return primitive

    logger.warning(
        "Unknown schema type %r, defaulting to Any (supported: %s)",
        kind,
        ", ".join(PRIMITIVES),
    )
    return ir.ANY


def _enum(values: Any) -> ir.TypeExpr:
    values = as_list(values)
    if not values:
        logger.warning("Malformed enum %r, defaulting to Any", values)
        return ir.ANY
    try:
        return ir.Enum(tuple(values))
    except TypeError as e:
        logger.warning("%s; defaulting to Any", e)
        return ir.ANY

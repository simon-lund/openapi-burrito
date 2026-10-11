"""``paths`` → operations."""

import logging
from collections.abc import Mapping
from typing import Any

from .. import ir
from . import naming
from .guards import as_dict, as_list, as_text
from .resolver import RefResolver
from .types import type_expr

logger = logging.getLogger(__name__)

BODY_SLOTS: tuple[tuple[str, ir.Slot], ...] = (
    # (MIME type, slot), first match wins. JSON (incl. +json) is matched first.
    ("application/x-www-form-urlencoded", ir.Slot.DATA),
    ("multipart/form-data", ir.Slot.FILES),
    ("application/octet-stream", ir.Slot.CONTENT),
)


def operations(
    spec: Mapping[str, Any], resolver: RefResolver
) -> tuple[ir.Operation, ...]:
    """One operation per path + method, in spec order."""
    result = []
    for path, path_item in as_dict(spec.get("paths")).items():
        logger.debug("Parsing path %s", path)
        path_item = as_dict(resolver.deref(path_item))
        path_params = as_list(path_item.get("parameters"))

        for key, op in path_item.items():
            try:
                method = ir.Method(str(key).upper())
            except ValueError:
                continue  # summary, description, parameters, servers, ...
            op = as_dict(op)

            params = naming.deconflict(
                _params(path_params + as_list(op.get("parameters")), resolver)
            )
            renames = {
                p.api_name: p.name for p in params if p.location is ir.Location.PATH
            }
            operation_id = op.get("operationId")
            result.append(
                ir.Operation(
                    method=method,
                    path=naming.rename_placeholders(str(path), renames),
                    params=params,
                    body=_body(op, resolver),
                    responses=_responses(op, resolver),
                    doc=_docstring(op, path_item),
                    tags=tuple(
                        t for t in as_list(op.get("tags")) if isinstance(t, str)
                    ),
                    operation_id=operation_id
                    if isinstance(operation_id, str)
                    else None,
                )
            )
    return tuple(result)


def _params(raw_params: list[Any], resolver: RefResolver) -> list[ir.Param]:
    # Parameters are unique by (name, in); operation-level overrides path-level
    merged: dict[tuple[Any, Any], dict[str, Any]] = {}
    for raw in raw_params:
        param = as_dict(resolver.deref(raw))
        merged[(param.get("name"), param.get("in"))] = param

    result = []
    for param in merged.values():
        name = param.get("name")
        try:
            location = ir.Location(str(param.get("in")))
        except ValueError:
            logger.warning(
                "Skipping parameter %r with unsupported location %r (supported: %s)",
                name,
                param.get("in"),
                ", ".join(ir.Location),
            )
            continue
        if not isinstance(name, str) or not name:
            logger.warning("Skipping %s parameter without a name", location)
            continue

        schema = param.get("schema", {})
        resolved = as_dict(resolver.deref(schema))
        result.append(
            ir.Param(
                name=naming.argument_name(name),
                api_name=name,
                location=location,
                type=type_expr(schema, resolver),
                # Path parameters are always required, whatever the spec says
                required=bool(param.get("required")) or location is ir.Location.PATH,
                default=ir.Default(resolved["default"])
                if "default" in resolved
                else None,
                doc=as_text(param.get("description")),
            )
        )
    return result


def _body(op: dict[str, Any], resolver: RefResolver) -> ir.Body | None:
    req = as_dict(resolver.deref(op.get("requestBody")))
    if not req:
        return None
    slot, schema = _body_slot(as_dict(req.get("content")))
    return ir.Body(
        slot=slot,
        type=type_expr(schema, resolver),
        required=bool(req.get("required")),
        doc=as_text(req.get("description")) or "Request body.",
    )


def _body_slot(content: dict[str, Any]) -> tuple[ir.Slot, Any]:
    """
    Picks the httpx slot for a request body. One content type per operation:
    JSON wins, then the BODY_SLOTS order; anything else falls back to raw
    ``content`` with a warning.
    """
    by_mime: dict[str, Any] = {}
    for mime, media in content.items():
        by_mime.setdefault(_base_mime(mime), as_dict(media).get("schema", {}))

    for mime, schema in by_mime.items():
        if _is_json(mime):
            return ir.Slot.JSON, schema
    for mime, slot in BODY_SLOTS:
        if mime in by_mime:
            return slot, by_mime[mime]

    logger.warning(
        "Request body has unsupported content type(s) %s, "
        "falling back to the raw 'content' slot",
        ", ".join(content) or "<none>",
    )
    return ir.Slot.CONTENT, {}


def _responses(op: dict[str, Any], resolver: RefResolver) -> tuple[ir.Response, ...]:
    """
    One entry per status code. Content type priority per response:
    JSON → the schema's type, octet-stream → bytes, no content → null.
    """
    result = []
    for code, resp in as_dict(op.get("responses")).items():
        if code == "default":
            # Ambiguous (could be success or error), skip it
            logger.debug("Skipping 'default' response, use a status code to include it")
            continue
        try:
            status = int(code)
        except (ValueError, TypeError):
            logger.warning("Skipping response with invalid status code %r", code)
            continue

        content = as_dict(as_dict(resolver.deref(resp)).get("content"))
        json_schemas = [
            as_dict(media).get("schema", {})
            for mime, media in content.items()
            if _is_json(mime)
        ]
        if json_schemas:
            type_ = type_expr(json_schemas[0], resolver)
        elif "application/octet-stream" in content:
            type_ = ir.BINARY
        elif not content:
            type_ = ir.NULL
        else:
            logger.warning(
                "Response %s has no supported content type "
                "(supported: application/json, */*+json, application/octet-stream)",
                code,
            )
            continue
        result.append(ir.Response(status, type_))
    return tuple(result)


def _docstring(op: dict[str, Any], path_item: dict[str, Any]) -> str:
    """Summary, description and (if not redundant) path description."""
    summary = as_text(op.get("summary"))
    description = as_text(op.get("description"))
    path_description = as_text(path_item.get("description"))
    if path_description in description:
        path_description = ""
    return "\n\n".join(filter(None, (summary, description, path_description)))


def _base_mime(mime: str) -> str:
    return mime.split(";")[0].strip().lower()


def _is_json(mime: str) -> bool:
    base = _base_mime(mime)
    return base == "application/json" or base.endswith("+json")

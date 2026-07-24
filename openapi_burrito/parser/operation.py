"""Operation parser for OpenAPI specifications."""

import logging
from dataclasses import replace
from typing import Any, Literal

from ..utils import normalize_path, to_snake_case
from .models import REQUIRED, UNSET, ParsedArg, ParsedOperation
from .resolver import RefResolver
from .sanitize import safe_bool, safe_status, sanitize
from .types import TypeTranslator

logger = logging.getLogger(__name__)

SUPPORTED_METHODS: tuple[str, ...] = (
    "GET",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "HEAD",
    "OPTIONS",
)
"""HTTP methods the generator supports (also drives the client template)."""

VALID_LOCATIONS = ("path", "query", "header", "cookie")
"""Valid parameter locations in OpenAPI spec."""

RESERVED_ARG_NAMES = {"self", "path", "json", "data", "files", "content"}
"""
Names taken by the generated method signatures: 'self' and 'path', plus the
fixed request-body slots. Parameters colliding with these (or with each other)
get renamed — the body is never renamed, since its name IS the runtime slot,
while renamed parameters still round-trip via the param location map.
"""

BODY_SLOTS = (
    # (MIME type, argument/slot name), first match wins.
    # JSON (incl. +json suffixes) is matched separately before these.
    ("application/x-www-form-urlencoded", "data"),
    ("multipart/form-data", "files"),
    ("application/octet-stream", "content"),
)


def _is_json_mime(mime: str) -> bool:
    base = mime.split(";")[0].strip().lower()
    return base == "application/json" or base.endswith("+json")


class OperationParser:
    """Parses all operations from an OpenAPI spec into a structured format."""

    def __init__(self, spec: dict[str, Any]) -> None:
        """
        Initializes the OperationParser.

        :param spec: The OpenAPI spec with internal $refs left unresolved.
        """
        self.spec = spec
        self.resolver = RefResolver(spec)
        self.type_translator = TypeTranslator(self.resolver)

    def parse(self) -> list[ParsedOperation]:
        """
        Parses all operations in the OpenAPI specification.

        :return: A list of ParsedOperation entries, one per path + method.
        """
        operations = []

        for path, path_item in self.spec.get("paths", {}).items():
            logger.debug("Parsing path %s", path)
            path_item = self.resolver.deref(path_item)

            # Paths can have shared parameters (e.g., /users/{id}) and description
            path_params = path_item.get("parameters", [])

            for method_name, op_data in path_item.items():
                method = method_name.upper()
                if method not in SUPPORTED_METHODS:
                    logger.debug("Skipping key %s in path %s", method_name, path)
                    continue

                raw_params = self._merge_parameters(
                    path_params, op_data.get("parameters", [])
                )
                params = self._parse_parameters(raw_params)
                body = self._parse_request_body(op_data)
                args = self._build_args(params, body)

                # Path placeholders must match the final (possibly renamed)
                # argument names so path.format(**path_vals) lines up.
                path_renames = {
                    arg.api_name: arg.name
                    for arg in args
                    if arg.in_ == "path" and arg.api_name
                }

                success_type, error_type = self._parse_responses(
                    op_data.get("responses", {})
                )
                operations.append(
                    ParsedOperation(
                        path=normalize_path(sanitize(path, mode="str"), path_renames),
                        method=method,
                        args=args,
                        success_type=success_type,
                        error_type=error_type,
                        doc=sanitize(
                            self._generate_docstring(op_data, path_item), mode="doc"
                        ),
                    )
                )

        return operations

    def _merge_parameters(
        self, path_params: list[Any], op_params: list[Any]
    ) -> list[dict[str, Any]]:
        """
        Dereferences and merges path-level and operation-level parameters.

        Per the OpenAPI spec, parameters are unique by (name, in) and
        operation-level definitions override path-level ones.
        """
        merged: dict[tuple[Any, Any], dict[str, Any]] = {}
        for param in path_params + op_params:
            param = self.resolver.deref(param)
            merged[(param.get("name"), param.get("in"))] = param
        return list(merged.values())

    def _parse_parameters(self, params: list[dict[str, Any]]) -> list[ParsedArg]:
        """Parses path, query, and header parameters of an operation."""
        parsed_params = []

        for param in params:
            schema = param.get("schema", {})
            name = param["name"]
            description = param.get("description", "")
            required = safe_bool(param, "required")
            # Translate the type; handles 'nullable' too -> '... | None'
            type_ = self.type_translator(schema)

            # Validate parameter location
            in_ = param.get("in", "")
            if in_ not in VALID_LOCATIONS:
                logger.warning(
                    "Skipping parameter %s with unsupported location %s, "
                    "only %s are supported",
                    name,
                    in_,
                    ", ".join(VALID_LOCATIONS),
                )
                continue

            # Determine default value based on presence in schema and required flag
            # (the schema may be a $ref, so check the resolved form)
            resolved_schema = self.resolver.deref(schema)
            if "default" in resolved_schema:
                default = repr(resolved_schema["default"])
            elif required:
                # Raises error if not provided when building request
                default = REQUIRED
            else:
                # Param will be omitted if not provided when building request
                default = UNSET

            parsed_params.append(
                ParsedArg(
                    name=to_snake_case(sanitize(name, mode="id")),
                    api_name=name,
                    type=type_,
                    in_=in_,
                    default=default,
                    doc=sanitize(description, mode="doc"),
                )
            )

        return parsed_params

    def _parse_request_body(self, op: dict[str, Any]) -> ParsedArg | None:
        """Parses the request body of an operation into its runtime body slot."""
        req_body = self.resolver.deref(op.get("requestBody"))
        if not req_body:
            return None

        content = req_body.get("content", {})
        required = safe_bool(req_body, "required")
        # Body has no default value per OpenAPI spec, but may be optional
        default = REQUIRED if required else UNSET
        doc = sanitize(req_body.get("description", "Request body."), mode="doc")

        slot = self._body_slot(content)
        if slot is None:
            logger.warning(
                "Request body has unsupported content type(s) %s, "
                "falling back to the raw 'content' slot",
                ", ".join(content) or "<none>",
            )
            slot = ("content", {})

        slot_name, schema = slot
        return ParsedArg(
            name=slot_name,
            api_name=None,
            type=self.type_translator(schema),
            in_="body",
            default=default,
            doc=doc,
        )

    @staticmethod
    def _body_slot(content: dict[str, Any]) -> tuple[str, Any] | None:
        """
        Maps the request body content types to a (slot name, schema) pair.

        Only one content type is supported per operation; JSON wins, then the
        BODY_SLOTS priority order.
        """
        normalized: dict[str, Any] = {}
        for mime, media in content.items():
            normalized.setdefault(mime.split(";")[0].strip().lower(), media)

        for base, media in normalized.items():
            if _is_json_mime(base):
                return "json", (media or {}).get("schema", {})

        for base, slot_name in BODY_SLOTS:
            if base in normalized:
                return slot_name, (normalized[base] or {}).get("schema", {})

        return None

    def _build_args(
        self, params: list[ParsedArg], body: ParsedArg | None
    ) -> list[ParsedArg]:
        """
        Merges, sorts, and de-collides parameters and body into a Python-safe
        function argument list.
        """
        args = params.copy()
        if body:
            args.append(body)

        # Sort args by category (path -> body -> query -> header -> cookie)
        order = ("path", "body", "query", "header", "cookie")
        args.sort(key=lambda a: order.index(a.in_))

        # Rename parameters that collide with reserved names or each other.
        # Path params come first so they keep their natural names.
        taken = set(RESERVED_ARG_NAMES)
        wrappers = {"query": "Query", "header": "Header", "cookie": "Cookie"}
        final_args = []
        for arg in args:
            if arg.in_ != "body":
                if arg.name in taken:
                    candidate = f"{arg.name}_{arg.in_}"
                    suffix = 2
                    while candidate in taken:
                        candidate = f"{arg.name}_{arg.in_}{suffix}"
                        suffix += 1
                    logger.info(
                        "Renamed colliding argument %s to %s", arg.name, candidate
                    )
                    arg = replace(arg, name=candidate)
                taken.add(arg.name)

            # Add type wrappers for readability and DevX
            if wrapper := wrappers.get(arg.in_):
                arg = replace(arg, type=f"{wrapper}[{arg.type}]")

            final_args.append(arg)

        return final_args

    def _parse_responses(self, responses: dict[str, Any]) -> tuple[str, str]:
        """
        Parses success and error response schemas of an operation.

        Note: Only JSON (incl. +json) and 'application/octet-stream' bodies
        are supported.
        """
        # status: (content_type, schema) - schema is None for binary/no-content
        parsed: dict[int, tuple[str, Any]] = {}

        for code, resp in responses.items():
            # OpenAPI 'default' is ambiguous (could be success or error), skip it
            if code == "default":
                logger.debug(
                    "Skipping 'default' response, use valid status code to include"
                )
                continue

            status = safe_status(code)
            if status is None:
                logger.warning("Skipping response with invalid status code %s", code)
                continue

            resp = self.resolver.deref(resp)
            content = resp.get("content", {})

            # Per-response content type priority: JSON > binary > no-content > skip
            json_schema = next(
                (
                    (media or {}).get("schema", {})
                    for mime, media in content.items()
                    if _is_json_mime(mime)
                ),
                None,
            )
            if json_schema is not None:
                parsed[status] = ("json", json_schema)
            elif "application/octet-stream" in content:
                parsed[status] = ("bytes", None)
            elif not content:
                # No content body (e.g., 204, or empty error responses)
                parsed[status] = ("none", None)
            else:
                logger.warning(
                    "Response %s has no supported content type "
                    "(supported: application/json, */*+json, "
                    "application/octet-stream)",
                    code,
                )

        return (
            self._aggregate_type(parsed, "success"),
            self._aggregate_type(parsed, "error"),
        )

    def _aggregate_type(
        self,
        parsed: dict[int, tuple[str, Any]],
        kind: Literal["success", "error"],
    ) -> str:
        """
        Aggregates 2xx (success) or 4xx/5xx (error) response types into a
        union, defaulting to 'Any'.
        """
        types = set()
        for status, (content_type, schema) in parsed.items():
            in_range = 200 <= status < 300 if kind == "success" else 400 <= status < 600
            if not in_range:
                continue

            if content_type == "none":
                types.add("None")
            elif content_type == "bytes":
                if kind == "success":
                    types.add("bytes")
                else:
                    logger.warning(
                        "Error response %s has unsupported binary content", status
                    )
            else:
                types.add(self.type_translator(schema))

        if not types or "Any" in types:
            # A union containing Any is just Any to a type checker
            return "Any"
        return " | ".join(sorted(types))

    def _generate_docstring(self, op: dict[str, Any], path_item: dict[str, Any]) -> str:
        """
        Synthesizes a unified docstring from operation and path metadata.
        """
        summary = op.get("summary", "").strip()
        op_desc = op.get("description", "").strip()
        path_desc = path_item.get("description", "").strip()
        paragraphs = (summary, op_desc, path_desc if path_desc not in op_desc else None)
        return "\n\n".join(filter(None, paragraphs))

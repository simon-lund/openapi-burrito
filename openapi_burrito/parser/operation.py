"""Operation parser for OpenAPI specifications."""

import logging
from dataclasses import replace
from http import HTTPMethod
from typing import Any

from ..utils import dig, normalize_path, to_snake_case
from .lookup import SchemaLookup
from .models import (
    REQUIRED,
    UNSET,
    ParsedArg,
    ParsedOperation,
    ParsedResponses,
    StatusCode,
)
from .sanitize import safe_bool, safe_status, sanitize
from .types import TypeTranslator

logger = logging.getLogger(__name__)


class OperationParser:
    """Parses all operations from an OpenAPI spec into a structured format."""

    valid_http_methods = (
        HTTPMethod.GET,
        HTTPMethod.POST,
        HTTPMethod.PUT,
        HTTPMethod.DELETE,
        HTTPMethod.PATCH,
        HTTPMethod.HEAD,
        HTTPMethod.OPTIONS,
    )
    """Valid HTTP methods in OpenAPI spec."""

    valid_locations = {"path", "query", "header", "cookie"}
    """Valid parameter locations in OpenAPI spec."""

    def __init__(self, resolved_spec: dict[str, Any]) -> None:
        """
        Initializes the OperationParser with a resolved OpenAPI specification.

        :param resolved_spec: The resolved OpenAPI specification dictionary.
        """
        self.resolved_spec = resolved_spec
        self.schema_lookup = SchemaLookup(resolved_spec)
        self.type_translator = TypeTranslator(self.schema_lookup)

    def __call__(self) -> list[ParsedOperation]:
        """Callable alias for parse method."""
        return self.parse()

    def parse(self) -> list[ParsedOperation]:
        """
        Parses all operations in the OpenAPI specification.

        :return: A list of dictionaries, each representing an operation
            with its details.
        """
        operations = []
        paths = self.resolved_spec.get("paths", {})

        for path, path_item in paths.items():
            logging.debug("Parsing path %s", path)

            # Paths can have shared parameters (e.g., /users/{id}) and description
            path_params = path_item.get("parameters", [])

            for method_name, op_data in path_item.items():
                method = self._get_valid_method(method_name)
                if not method:
                    logger.debug(
                        "Skipping invalid HTTP method %s in path %s",
                        method_name,
                        path,
                    )
                    continue

                all_raw_params = path_params + op_data.get("parameters", [])
                params = self._parse_parameters(all_raw_params)
                body = self._parse_request_body(op_data)

                operations.append(
                    ParsedOperation(
                        path=normalize_path(sanitize(path, mode="str")),
                        method=method.value,
                        args=self._build_args(params, body),
                        responses=self._parse_responses(op_data.get("responses", {})),
                        doc=sanitize(
                            self._generate_docstring(op_data, path_item), mode="doc"
                        ),
                    )
                )

        return operations

    def _get_valid_method(self, method_name: str) -> HTTPMethod | None:
        """Helper to validate and filter HTTP methods."""
        try:
            method = HTTPMethod(method_name.upper())
            if method in self.valid_http_methods:
                return method
        except ValueError:
            pass

        return None

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
            if in_ not in self.valid_locations:
                logger.warning(
                    "Skipping parameter %s with unsupported location %s, "
                    "only %s are supported",
                    param.get("name"),
                    in_,
                    ", ".join(self.valid_locations),
                )
                continue

            # Determine default value based on presence in schema and required flag
            if "default" in schema:
                default = repr(schema["default"])
            elif required:
                # Raises error if not provided when building request
                default = REQUIRED
            else:
                # Param will be omitted if not provided when building request
                default = UNSET

            parsed_param = ParsedArg(
                name=to_snake_case(sanitize(name, mode="id")),
                api_name=name,
                type=type_,
                in_=in_,
                required=required,
                default=default,
                doc=sanitize(description, mode="doc"),
            )

            parsed_params.append(parsed_param)

        return parsed_params

    def _parse_request_body(self, op: dict[str, Any]) -> ParsedArg | None:
        """Parses the request body of an operation."""
        req_body = op.get("requestBody")
        if not req_body:
            return None

        content = req_body.get("content", {})
        required = safe_bool(req_body, "required")
        # Body has no default value per OpenAPI spec, but may be optional
        default = REQUIRED if required else UNSET
        doc = sanitize(req_body.get("description", "Request body."), mode="doc")

        # Prioritized list of supported MIME types with argument names
        # since we only support one content type per path + method combination
        mime_types = [
            ("application/json", "json"),
            ("application/x-www-form-urlencoded", "data"),
            ("multipart/form-data", "files"),
            ("application/octet-stream", "content"),
        ]

        for mime, arg_name in mime_types:
            if mime in content:
                schema = content[mime].get("schema", {})
                return ParsedArg(
                    name=to_snake_case(arg_name),
                    api_name=None,
                    type=self.type_translator(schema),
                    in_="body",
                    required=required,
                    default=default,
                    doc=doc,
                )

        logger.warning(
            "Request body has unsupported content type, only supported types are: %s",
            ", ".join(mt for mt, _ in mime_types),
        )
        return ParsedArg(
            name="data",
            api_name=None,
            type="Any",
            in_="body",
            required=required,
            default=default,
            doc=doc,
        )

    def _build_args(
        self, params: list[ParsedArg], body: ParsedArg | None
    ) -> list[ParsedArg]:
        """
        Merges and sorts parameters and body into a Python-safe function arguments list.
        """
        args = params.copy()

        if body:
            # Check for name collisions (e.g. if a query param is named 'json')
            existing_names = {p.name for p in args}
            if body.name in existing_names:
                new_name = f"{body.name}_body"  # Simple rename to prevent SyntaxError
                logger.info(
                    "Renamed colliding body arg %s to %s",
                    body.name,
                    new_name,
                )
                body = replace(body, name=new_name)

            args.append(body)

        # Add type wrappers for readability and DevX
        wrappers = {"query": "Query", "header": "Header", "cookie": "Cookie"}
        final_args = []
        for arg in args:
            if wrapper := wrappers.get(arg.in_):
                arg = replace(arg, type=f"{wrapper}[{arg.type}]")
            elif arg.in_ not in ("path", "body"):
                logger.warning(
                    "Unknown parameter location %s for %s",
                    arg.in_,
                    arg.name,
                )

            final_args.append(arg)

        # Sort params by category (path -> body -> query -> header -> cookie)
        order = ("path", "body", "query", "header", "cookie")
        return sorted(final_args, key=lambda p: order.index(p.in_))

    def _parse_responses(self, responses: dict[str, Any]) -> ParsedResponses:
        """
        Parses success and error response schemas of an operation.

        Note: For now we only support 'application/json' and 'application/octet-stream'.
        """
        # status: (content_type, schema) - schema is None for binary
        parsed_responses: dict[StatusCode, tuple[str, Any]] = {}

        for code, resp in responses.items():
            # OpenAPI 'default' is ambiguous (could be success or error), skip it
            if code == "default":
                logger.debug(
                    "Skipping 'default' response, use valid status code to include"
                )
                continue

            status = safe_status(code)
            if not status:
                logger.warning("Skipping response with invalid status code %s", code)
                continue

            content = resp.get("content", {})

            # Per-response content type priority: JSON > binary > no-content > skip
            if json_schema := dig(content, ("application/json", "schema")):
                parsed_responses[status] = ("json", json_schema)
            elif "application/octet-stream" in content:
                parsed_responses[status] = ("bytes", None)
            elif not content:
                # No content body (e.g., 204, or empty error responses)
                parsed_responses[status] = ("none", None)
            else:
                logger.warning(
                    "Response %s has no supported content type, "
                    "(supported: application/json, application/octet-stream)",
                    code,
                )

        return ParsedResponses(
            success_type=self._parse_success_type(parsed_responses),
            error_type=self._parse_error_type(parsed_responses),
        )

    def _parse_success_type(
        self, parsed_responses: dict[StatusCode, tuple[str, Any]]
    ) -> str:
        """Aggregates all 2xx response types into a union, defaulting to 'Any'."""
        success_types = set()
        for status, (content_type, schema) in parsed_responses.items():
            if status.is_success:
                if content_type == "none":
                    success_types.add("None")
                elif content_type == "bytes":
                    success_types.add("bytes")
                else:
                    success_types.add(self.type_translator(schema))

        # Clean up success list
        if "Any" in success_types:
            success_types.discard("Any")
            sorted_types = sorted(success_types) + ["Any"]
        else:
            sorted_types = sorted(success_types)

        return " | ".join(sorted_types) if sorted_types else "Any"

    def _parse_error_type(
        self, parsed_responses: dict[StatusCode, tuple[str, Any]]
    ) -> str:
        """Aggregates 4xx/5xx response types into a union, defaulting to 'Any'."""
        error_types = set()
        for status, (content_type, schema) in parsed_responses.items():
            is_error = status.is_client_error or status.is_server_error
            if is_error:
                if content_type == "none":
                    error_types.add("None")
                elif content_type == "json" and schema:
                    error_types.add(self.type_translator(schema))
                else:
                    logger.warning(
                        "Error response %s has unsupported content type %s",
                        status.value,
                        content_type,
                    )

        # Clean up error list
        if "Any" in error_types:
            error_types.discard("Any")
            sorted_types = sorted(error_types) + ["Any"]
        else:
            sorted_types = sorted(error_types)

        return " | ".join(sorted_types) if sorted_types else "Any"

    def _generate_docstring(self, op: dict[str, Any], path_item: dict[str, Any]) -> str:
        """
        Synthesizes a unified docstring from operation and path metadata.
        """
        summary = op.get("summary", "").strip()
        op_desc = op.get("description", "").strip()
        path_desc = path_item.get("description", "").strip()
        paragraphs = filter(
            None, (summary, op_desc, path_desc if path_desc not in op_desc else None)
        )
        return "\n\n".join(
            paragraphs or ["No description provided. See OpenAPI spec for details."]
        )

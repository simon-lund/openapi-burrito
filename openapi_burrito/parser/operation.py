import logging
from http import HTTPMethod, HTTPStatus
from typing import Any

from .schema import build_schema_lookup
from .types import TypeTranslator
from ..utils import dig, to_status

logger = logging.getLogger(__name__)

_REQUIRED_SENTINEL = "REQUIRED"
"""
Usually required arguments have to be placed before optional arguments in Python function
definitions. This sentinel can be used to mark an argument as required even if it has no
default value, allowing it to be placed after optional arguments.

This allows us to maintain the order of parameters by group, i.e.
path -> body -> query 
"""


_UNSET_SENTINEL = "UNSET"
"""
Used to distinguish between an explicit JSON null (None) and a missing value (UNSET).
This allows the client to omit fields from the request entirely if they aren't provided
and keep fields that are explicitly set to null.
"""

class OperationParser:
    """Parses all operations from an OpenAPI spec into a structured format."""

    supported_http_methods = (
        HTTPMethod.GET,
        HTTPMethod.POST,
        HTTPMethod.PUT,
        HTTPMethod.DELETE,
        HTTPMethod.PATCH
    )

    def __init__(self, resolved_spec: dict[str, Any]) -> None:
        """
        Initializes the OperationParser with a resolved OpenAPI specification.

        :param resolved_spec: The resolved OpenAPI specification dictionary.
        """
        self.resolved_spec = resolved_spec
        self.schema_lookup = build_schema_lookup(resolved_spec)
        self.type_translator = TypeTranslator(self.schema_lookup)

    def __call__(self) -> list[dict[str, Any]]:
        """Callable alias for parse method."""
        return self.parse()

    def parse(self) -> list[dict[str, Any]]:
        """
        Parses all operations in the OpenAPI specification.

        :return: A list of dictionaries, each representing an operation with its details.
        """
        operations = []
        paths = self.resolved_spec.get("paths", {})

        for path, path_item in paths.items():
            logging.info("Parsing path: %s", path, extra={"path": path})

            # Paths can have shared parameters (e.g., /users/{id}) and description
            path_params = path_item.get("parameters", [])

            for method, op in path_item.items():
                method = method.upper()
                if method not in self.supported_http_methods:
                    logger.warning("Skipping unsupported HTTP method '%s' for path '%s'", method, path, extra={
                        "path": path,
                        "method": method,
                        "supported_methods": list(self.supported_http_methods)
                    })
                    continue

                params = self._parse_parameters(path_params + op.get("parameters", []))
                body = self._parse_request_body(op)

                operations.append({
                    "path": path,
                    "method": method,
                    "args": self._build_args(params, body),
                    "responses": self._parse_responses(op.get("responses", {})),
                    "doc": self._generate_docstring(op, path_item)
                })

        return operations

    def _parse_parameters(self, params: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Parses path, query, and header parameters of an operation."""
        parsed_params = []

        for param in params:
            p_schema = param.get("schema", {})
            p_required = param.get("required", False)
            p_type = self.type_translator(p_schema)  # Translate the type; handles 'nullable' too -> '... | None'
            # If no default value is provided, we use "UNSET" sentinel to distinguish between omitted and explicit nulls (= None)
            p_default = p_schema.get("default", _UNSET_SENTINEL)

            parsed_param = {
                "name": param.get("name"),
                "type": p_type,
                "in": param.get("in"),  # path, query, header, cookie
                "required": p_required,
                "doc": param.get("description", "")
            }

            # First, mark required parameters with the REQUIRED sentinel
            # If there is a default value for a required parameter, we overwrite it in the next step
            if p_required:
                parsed_param["default"] = _REQUIRED_SENTINEL

            if (p_required and not p_default == _UNSET_SENTINEL) or not p_required:
                # repr() required to get proper string representation of e.g. strings with quotes
                parsed_param["default"] = repr(p_default) if p_default != _UNSET_SENTINEL else _UNSET_SENTINEL

            parsed_params.append(parsed_param)

        return parsed_params

    def _parse_request_body(self, op: dict[str, Any]) -> dict[str, Any] | None:
        """Parses the request body of an operation."""
        req_body = op.get("requestBody")
        if not req_body:
            return None

        content = req_body.get("content", {})
        required = req_body.get("required", False)
        # As per OpenAPI spec, body does not have a default value but may be optional
        default = _REQUIRED_SENTINEL if required else _UNSET_SENTINEL
        doc = req_body.get("description", "Request body.")

        # Prioritized list of supported MIME types with argument names
        # since we only support one content type per path + method combination
        mime_types = [
            ("application/json", "json"),
            ("application/x-www-form-urlencoded", "data"),
            ("multipart/form-data", "files"),
            ("application/octet-stream", "content")
        ]

        for mime, arg_name in mime_types:
            if mime not in content:
                logger.warning(
                    "Request body content type '%s' not supported; skipping.", mime, extra={
                        "supported_content_types": list(content.keys())
                    }
                )
                continue

            schema = content[mime].get("schema", {})
            p_type = self.type_translator(schema)
            return {"arg": arg_name, "type": p_type, "required": required, "default": default, "doc": doc}
        else:
            logger.warning(
                "No supported content types found in request body; defaulting to 'Any'.",
                extra={"available_content_types": list(content.keys())}
            )
            return {"arg": "data", "type": "Any", "required": required, "default": default, "doc": doc}

    def _build_args(self, params: list, body: dict | None) -> list:
        """
        Merges and sorts parameters and body into a Python-safe function arguments list.
        """
        args = params.copy()

        if body:
            # Check for name collisions (e.g. if a query param is named 'json')
            existing_names = {p["name"] for p in args}
            arg_name = body["arg"]
            if arg_name in existing_names:
                arg_name = f"{arg_name}_body"  # Simple rename to prevent SyntaxError
                logger.warning(f"Request body argument name '{arg_name}' collides with existing parameter names; renaming to avoid conflict.", extra={
                    "existing_names": existing_names,
                    "new_name": arg_name
                })

            args.append({
                "name": arg_name,
                "type": body["type"],
                "in": "body",
                "required": body["required"],
                "default": body["default"],
                "doc": body["doc"]
            })

        # To improve readability and DevX we add type wrappers to indicate the category of parameters
        # for query, header, and cookie parameters.
        for arg in args:
            if arg["in"] == "query":
                arg["type"] = f"Query[{arg['type']}]"
            elif arg["in"] == "header":
                arg["type"] = f"Header[{arg['type']}]"
            elif arg["in"] == "cookie":
                arg["type"] = f"Cookie[{arg['type']}]"
            elif arg["in"] == "path" or arg["in"] == "body":
                # No special wrapper for path and body parameters
                pass
            else:
                logger.warning(f"Unknown parameter location '{arg['in']}' for parameter '{arg['name']}'.")


        # Sort params by category (path -> body -> query -> header -> cookie) [Note: This is stable sort]
        return sorted(args, key=lambda p: ("path", "body", "query", "header", "cookie").index(p["in"]))

    def _parse_responses(self, responses: dict[str, Any]) -> dict[str, str]:
        """
        Parses success and error response schemas of an operation.

        Notes:
            - Only 'application/json' content types are considered.
            - Only one success response type is selected (prioritizing OK [200], Created [201], Accepted [202]).
        """
        # Pre-filter: Separate JSON responses from non-JSON (keyed by HTTPStatus for easy comparison)
        json_responses: dict[HTTPStatus, Any] = {}
        for code, resp in responses.items():
            status = to_status(code)
            schema = dig(resp, ("content", "application/json", "schema"))
            if schema and status:
                json_responses[status] = schema
            elif status and status != HTTPStatus.NO_CONTENT:
                logger.warning(
                    f"Response {code} ignored: No 'application/json' schema found."
                )
            elif not status:
                logger.warning(
                    f"Response code '{code}' is not a valid HTTP status code; skipping."
                )


        # Success (2xx)
        prioritized = [HTTPStatus.OK, HTTPStatus.CREATED, HTTPStatus.ACCEPTED]
        success_code = next(
            # First, check prioritized status codes
            (s for s in prioritized if s in json_responses),
            # Then, check for any 2xx status. If no 2xx found, return None
            next((s for s in json_responses if s.is_success), None)
        )

        response_type = "Any"
        if success_code == HTTPStatus.NO_CONTENT:
            response_type = "None"
        elif success_code in json_responses:
            response_type = self.type_translator(json_responses[success_code])
        else:
            logger.warning(
                "No successful (2xx) JSON response schema found; defaulting to 'Any'.",
                extra={"found_success_responses": [s for s in json_responses if s.is_success]}
            )

        # Aggregate errors (non-2xx)
        errors = {
            self.type_translator(schema)
            for status, schema in json_responses.items()
            if status.is_client_error or status.is_server_error
        }

        if "Any" in errors:
            logger.warning(
                "One or more error responses have no defined schema; adding 'Any' to error types.",
                extra={"error_statuses": [s for s in json_responses if s.is_client_error or s.is_server_error]}
            )
            errors = list(filter(lambda e: e != "Any", errors)) + ["Any"]

        error_types = " | ".join(errors)

        return {"response_type": response_type, "error_types": error_types}

    def _generate_docstring(self, op: dict, path_item: dict) -> str:
        """
        Synthesizes a unified docstring from operation and path metadata.
        """
        summary = op.get("summary", "").strip()
        op_desc = op.get("description", "").strip()
        path_desc = path_item.get("description", "").strip()
        paragraphs = filter(None, (summary, op_desc, path_desc if path_desc not in op_desc else None))
        return "\n\n".join(paragraphs or ["No description provided. See OpenAPI spec for details."])

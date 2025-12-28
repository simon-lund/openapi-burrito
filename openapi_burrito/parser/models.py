"""Data models for parsed API operations and schemas."""

from dataclasses import dataclass
from typing import Literal

# Sentinel values
REQUIRED = "REQUIRED"
"""
Sentinel to mark required arguments in function signatures.

Required arguments must usually be placed before optional arguments in Python.
This sentinel allows required arguments to be placed after optional ones,
maintaining parameter order by group (path -> body -> query -> header -> cookie).
"""

UNSET = "UNSET"
"""
Sentinel to distinguish between omitted parameters and explicit None values.

Used for parameters with no default value to enable distinction between:
- Parameter not provided (UNSET)
- Parameter explicitly set to None
"""


class StatusCode:
    """
    A wrapper for HTTP status codes that supports any numeric code.

    Unlike HTTPStatus, this works with custom status codes (e.g., 458, 499)
    that some APIs use for application-specific errors.
    """

    def __init__(self, code: int):
        self.value = code

    @property
    def is_success(self) -> bool:
        return 200 <= self.value < 300

    @property
    def is_client_error(self) -> bool:
        return 400 <= self.value < 500

    @property
    def is_server_error(self) -> bool:
        return 500 <= self.value < 600

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, StatusCode):
            return self.value == other.value
        return NotImplemented


@dataclass
class ParsedArg:
    """Represents a parsed API argument (path, query, header, cookie, or body)."""

    name: str
    """Python-safe snake_case name"""
    api_name: str | None
    """Original API parameter name from the spec (empty for body)"""
    type: str
    """Python type annotation string"""
    in_: Literal["path", "query", "header", "cookie", "body"]
    """Argument location"""
    required: bool
    """Whether the argument is required"""
    default: str
    """Default value (REQUIRED, UNSET, or repr() of actual default)"""
    doc: str = ""
    """Sanitized documentation"""


@dataclass
class ParsedResponses:
    """Represents parsed response types for an operation."""

    success_type: str
    """Type annotation for 2xx responses"""
    error_type: str | None
    """Type annotation for 4xx/5xx responses"""


@dataclass
class ParsedOperation:
    """Represents a fully parsed API operation."""

    method: str
    """HTTP method (GET, POST, etc.)"""
    path: str
    """API path"""
    args: list[ParsedArg]
    """All operation arguments (path, query, header, cookie, body)"""
    responses: ParsedResponses
    """Response type information"""
    doc: str = ""
    """Operation documentation"""


@dataclass
class ParsedProperty:
    """Represents a property in a schema."""

    name: str
    """Python-safe property name"""
    type: str
    """Python type annotation string"""
    required: bool
    """Whether the property is required"""
    doc: str = ""
    """Property documentation"""
    read_only: bool = False
    """Whether the property is read-only"""
    write_only: bool = False
    """Whether the property is write-only"""
    default: str | None = None
    """String representation of the default value, if any"""


@dataclass
class ParsedModel:
    """Represents a parsed schema/model."""

    name: str
    """Model class name"""
    properties: list[ParsedProperty]
    """List of model properties"""
    doc: str = ""
    """Model documentation"""
    ref_name: str = ""
    """Original $ref name if applicable"""

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


@dataclass
class ParsedArg:
    """Represents a parsed API argument (path, query, header, cookie, or body)."""

    name: str
    """Python-safe snake_case name"""
    api_name: str | None
    """Original API parameter name from the spec (None for body)"""
    type: str
    """Python type annotation string"""
    in_: Literal["path", "query", "header", "cookie", "body"]
    """Argument location"""
    default: str
    """Default value (REQUIRED, UNSET, or repr() of actual default)"""
    doc: str = ""
    """Sanitized documentation"""


@dataclass
class ParsedResponses:
    """Represents parsed response types for an operation."""

    success_type: str
    """Type annotation for 2xx responses"""
    error_type: str
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
    """Original wire-format key, verbatim (TypedDict keys must match the JSON)"""
    type: str
    """Python type annotation string (optional props pre-wrapped in NotRequired)"""
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
    functional: bool = False
    """
    TypedDict has two spellings. Class syntax writes keys as attribute names::

        class User(TypedDict):
            name: str

    That only works when every key is a valid identifier and not a keyword —
    ``class: str`` is a SyntaxError, ``user-name: str`` too. Renaming keys is
    not an option: a TypedDict is a plain dict at runtime, so its keys must
    match the JSON on the wire exactly. For such models the template uses the
    functional spelling instead, where keys are arbitrary string literals::

        User = TypedDict("User", {"user-name": str, "class": str})

    This flag tells the template which spelling to render.
    """

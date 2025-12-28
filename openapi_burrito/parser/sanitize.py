"""
Security-critical sanitization utilities for code generation.

**MODIFYING THESE FUNCTIONS HAS SECURITY IMPLICATIONS**

See: CVE-2020-15142, GHSA-9x4c-63pf-525f
"""

import builtins
import keyword
import re
from typing import Any, Literal

from .models import StatusCode

# Reserved words that would shadow Python builtins or cause issues
RESERVED_WORDS = (
    set(dir(builtins))  # list, dict, str, int, type, id, etc.
    | {"self", "cls", "true", "false", "null", "undefined"}
) - {"id"}  # 'id' is commonly used in APIs, allow it

SanitizeType = Literal["id", "str", "doc"]


def sanitize(value: str, mode: SanitizeType = "str") -> str:
    """
    Unified sanitization function for code generation.

    **SECURITY CRITICAL** - Prevents code injection via malicious OpenAPI specs.

    See: CVE-2020-15142, GHSA-9x4c-63pf-525f

    :param value: The raw string to sanitize
    :param mode: The sanitization mode:
        - "id": Python identifier (class names, property names, parameters)
        - "str": String literal (paths, enum values)
        - "doc": Docstring content
    :return: Sanitized string safe for use in generated Python code
    :raises ValueError: If the value cannot be sanitized into a valid identifier
    """
    if mode == "id":
        return _sanitize_identifier(value)
    elif mode == "str":
        return _sanitize_string(value)
    elif mode == "doc":
        return _sanitize_docstring(value)
    else:
        raise ValueError(f"Unknown sanitization mode: {mode}")


def _sanitize_identifier(value: str) -> str:
    """Converts an arbitrary string into a valid Python identifier."""
    # Replace non-alphanumeric with underscore
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", value)

    # Collapse multiple underscores
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")

    # Handle empty result - should never happen with valid OpenAPI input
    if not sanitized:
        raise ValueError(
            f"Cannot create identifier from empty or invalid value: '{value}'"
        )

    # Handle names starting with digit
    if sanitized[0].isdigit():
        sanitized = f"_{sanitized}"

    # Handle Python keywords (if, class, return, etc.)
    if keyword.iskeyword(sanitized):
        sanitized = f"{sanitized}_"

    # Handle builtins (list, dict, str, type, etc.)
    if sanitized in RESERVED_WORDS:
        sanitized = f"{sanitized}_"

    # Final validation - should never fail after above transformations
    if not sanitized.isidentifier():
        raise ValueError(
            f"Failed to create valid identifier from: '{value}' (got: '{sanitized}')"
        )

    return sanitized


def _sanitize_string(value: str) -> str:
    """Escapes a string for safe inclusion in a Python string literal."""
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("'", "\\'")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def _sanitize_docstring(value: str) -> str:
    """Escapes a string for safe inclusion in a triple-quoted docstring."""
    return value.replace('"""', r"\"\"\"").replace("'''", r"\'\'\'")


def safe_bool(d: dict[str, Any], key: str, default: bool = False) -> bool:
    """
    Safely extracts a boolean from a dict, preventing code injection.

    OpenAPI specs can come from untrusted sources. Without explicit bool(),
    a malicious spec could inject arbitrary values that evaluate as truthy.
    """
    return bool(d.get(key, default))


def safe_status(code: str) -> StatusCode | None:
    """
    Safely convert a response code string to a StatusCode.
    Returns None for non-numeric strings like 'default'.
    """
    try:
        return StatusCode(int(code))
    except (ValueError, TypeError):
        return None

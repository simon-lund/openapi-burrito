import re
from collections.abc import Iterable
from typing import Any


def dig(data: Any, path: Iterable[Any], default: Any = None) -> Any:
    """
    Safely navigates a nested dict/list structure.
    Returns default if any key is missing or an index is out of bounds.

    :param data: The initial data structure (dict or list).
    :param path: An iterable of keys/indices to traverse the structure.
    :param default: The value to return if any key/index is missing.
    :return: The value found at the end of the path, or default.
    """
    for key in path:
        try:
            data = data[key]
        except (KeyError, TypeError, IndexError):
            return default
    return data


def to_snake_case(name: str) -> str:
    """
    Converts camelCase or PascalCase to snake_case.
    Handles acronyms gracefully (e.g., HTTPResponse -> http_response).
    """
    # Insert underscore between lower+upper (e.g., camelCase -> camel_Case)
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    # Insert underscore between lower/digit+upper
    # (e.g., camel_Case -> camel_Case, HTTP -> HTTP)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def normalize_path(path: str) -> str:
    """
    Converts path parameter names to snake_case.
    e.g., /pet/{petId} -> /pet/{pet_id}
    """
    return re.sub(r"\{([^}]+)\}", lambda m: "{" + to_snake_case(m.group(1)) + "}", path)

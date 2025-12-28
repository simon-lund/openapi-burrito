from http import HTTPStatus
from typing import Any, Iterable

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


def to_status(code: str) -> HTTPStatus | None:
    """Safely convert a response code string to HTTPStatus, returning None for 'default' or invalid codes."""
    if code == "default":
        return None
    try:
        return HTTPStatus(int(code))
    except (ValueError, TypeError):
        return None
"""
Runtime support for generated clients.

This module is copied verbatim into every generated package as ``_runtime.py``.
It is the reason generated clients have no dependency on openapi-burrito: the
runtime is vendored, not templated. Everything here must therefore be
self-contained (stdlib + httpx only) and must not import from the generator.
"""

from __future__ import annotations

import fnmatch
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Final, cast

import httpx

__all__ = [
    "REQUIRED",
    "UNSET",
    "AsyncHandlerT",
    "AsyncMiddlewareT",
    "Cookie",
    "HandlerT",
    "Header",
    "MiddlewareT",
    "Path",
    "Query",
    "RequiredType",
    "Response",
    "ResponseError",
    "UnsetType",
]

# Type wrappers for parameter locations. They are documentation in the
# generated signatures (so a reader can tell a header from a query param);
# routing is done by the client's _PARAM_MAP, not by these annotations.
type Query[T] = Annotated[T, "query"]
"""Query parameter type wrapper."""
type Header[T] = Annotated[T, "header"]
"""Header parameter type wrapper."""
type Cookie[T] = Annotated[T, "cookie"]
"""Cookie parameter type wrapper."""
type Path[T] = Annotated[T, "path"]
"""Path parameter type wrapper."""

type HandlerT = Callable[[httpx.Request], httpx.Response]
"""A handler that turns a request into a response (innermost: actual send)."""

type MiddlewareT = Callable[[httpx.Request, HandlerT], httpx.Response]
"""Middleware function type alias: (request, call_next) -> response."""

type AsyncHandlerT = Callable[[httpx.Request], Awaitable[httpx.Response]]
"""Async handler that turns a request into a response (innermost: actual send)."""

type AsyncMiddlewareT = Callable[
    [httpx.Request, AsyncHandlerT], Awaitable[httpx.Response]
]
"""Async middleware function type alias: async (request, call_next) -> response."""


class UnsetType:
    """
    Sentinel type for parameters that were not passed at all.

    None cannot play this role: None is JSON null, a value a caller may
    legitimately want to send. UNSET means "omit this parameter from the
    request entirely".
    """

    def __repr__(self) -> str:
        return "UNSET"


class RequiredType:
    """
    Sentinel type for required parameters.

    Signatures are ordered by location (path, body, query, header, cookie),
    so a required parameter can follow an optional one. Python only allows
    that if it has a default; REQUIRED is that placeholder. If it is still
    present when the request is built, a TypeError is raised.
    """

    def __repr__(self) -> str:
        return "REQUIRED"


# We cast to Any to "pretend" to the type checker that this is a valid
# default for any type hint, keeping the function signatures clean.
UNSET: Final[Any] = cast(Any, UnsetType())
"""
Sentinel default for optional parameters. See UnsetType.

Example:
    >>> def foo(a: str | None = UNSET):
    ...     if isinstance(a, UnsetType):
    ...         return "a is unset"
    ...     return f"set to {a}"
    >>> foo()
    'a is unset'
    >>> foo("5")
    'set to 5'
    >>> foo(None)
    'set to None'
"""

REQUIRED: Final[Any] = cast(Any, RequiredType())
"""
Sentinel default for required parameters. See RequiredType.

Example:
    >>> def foo(a: str = REQUIRED):
    ...     if isinstance(a, RequiredType):
    ...         raise TypeError("Missing required parameter 'a'")
    ...     return f"set to {a}"
    >>> foo("5")
    'set to 5'
    >>> foo()  # Raises TypeError
"""


@dataclass
class Response[T, E]:
    """
    A transparent, typed proxy for httpx.Response.
    Delegates all standard attributes to httpx while providing
    auto-parsing for JSON and NDJSON formats.
    """

    _response: httpx.Response

    def __getattr__(self, name: str) -> Any:
        """Forward all remaining httpx attributes (cookies, url, etc)."""
        if name == "_response":
            # Guard against infinite recursion when _response itself is
            # missing (e.g. during copy/pickle before __init__ ran)
            raise AttributeError(name)
        return getattr(self._response, name)

    @property
    def data(self) -> T | None:
        """Typed success body. None if not a 2xx response."""
        return cast("T | None", self._parse()) if self.is_success else None

    @property
    def error(self) -> E | None:
        """Typed error body. None if not a 4xx/5xx response."""
        return cast("E | None", self._parse()) if self.is_error else None

    def unwrap(self) -> T:
        """
        Returns the typed success body, raising ResponseError for non-2xx.

        Unlike .data (which is T | None and needs a None-check even after
        an is_success guard), unwrap() gives the type checker a plain T:

            pet = api.GET("/pet/{pet_id}", pet_id=1).unwrap()
        """
        if not self.is_success:
            raise ResponseError(self)
        return cast("T", self._parse())

    # Explicitly typed passthroughs (the __getattr__ fallback is invisible
    # to type checkers, so the common surface is declared here)
    @property
    def status_code(self) -> int:
        return self._response.status_code

    @property
    def headers(self) -> httpx.Headers:
        return self._response.headers

    @property
    def content(self) -> bytes:
        return self._response.content

    @property
    def text(self) -> str:
        return self._response.text

    @property
    def is_informational(self) -> bool:
        """Helper for 1xx responses."""
        return self._response.is_informational

    @property
    def is_success(self) -> bool:
        """Helper for 2xx responses."""
        return self._response.is_success

    @property
    def is_redirect(self) -> bool:
        """Helper for 3xx responses."""
        return self._response.is_redirect

    @property
    def is_client_error(self) -> bool:
        """Helper for 4xx responses."""
        return self._response.is_client_error

    @property
    def is_server_error(self) -> bool:
        """Helper for 5xx responses."""
        return self._response.is_server_error

    @property
    def is_error(self) -> bool:
        """Helper for 4xx or 5xx responses."""
        return self.is_client_error or self.is_server_error

    def json(self) -> Any:
        """Raw JSON body, untyped. Use .data / .error for typed access."""
        return self._response.json()

    def _parse(self) -> Any:
        """
        Parses JSON or NDJSON based on Content-Type.
        Falls back to .content if parsing fails or no body.
        """
        if not self._response.content:
            return None

        # Ignore charset etc. after the semicolon
        ctype = self.headers.get("content-type", "").lower().split(";")[0]

        is_standard_json = ctype == "application/json" or fnmatch.fnmatch(
            ctype, "*+json"
        )
        is_ndjson = any(sub in ctype for sub in ["ndjson", "jsonl", "json-seq"])

        try:
            if is_standard_json:
                return self._response.json()

            if is_ndjson:
                return [
                    json.loads(line)
                    for line in self._response.text.splitlines()
                    if line.strip()
                ]
        except ValueError:
            # Malformed JSON: fall through to the raw bytes
            pass

        return self._response.content

    def __repr__(self) -> str:
        """Dynamic representation using the actual class name."""
        return f"<{self.__class__.__name__} [{self.status_code}]>"


class ResponseError(Exception):
    """
    Raised by Response.unwrap() when the response is not a 2xx.

    The full typed response stays available as .response, so error bodies
    can still be inspected: exc.response.error / exc.response.status_code.
    """

    def __init__(self, response: Response[Any, Any]) -> None:
        super().__init__(f"Request failed with status {response.status_code}")
        self.response: Response[Any, Any] = response


type Locations = Mapping[str, Mapping[str, str]]
"""
Where each Python argument of one operation goes on the wire:
``{"query": {"python_name": "apiName", ...}, "header": {...}, ...}``.
Path arguments map to themselves (the path template uses the Python names).
"""

_PATH_PLACEHOLDER = re.compile(r"\{([^}]+)\}")


def prepare_request(
    client: httpx.Client | httpx.AsyncClient,
    method: str,
    path: str,
    *,
    json: Any = None,
    data: Any = None,
    files: Any = None,
    content: Any = None,
    params: Mapping[str, Any],
    locations: Locations | None,
) -> httpx.Request:
    """
    Validates keyword arguments, routes them to their wire locations, and
    builds the httpx request.

    :param params: The keyword arguments the caller passed (may contain the
        UNSET / REQUIRED sentinels).
    :param locations: The operation's location map, or None if the path is
        not in the spec — then placeholders in ``path`` are filled from
        ``params`` and everything else is sent as query parameters.
    """
    for name, value in params.items():
        if isinstance(value, RequiredType):
            raise TypeError(f"Missing required parameter: {name}")

    # Drop UNSET; keep None (it is JSON null)
    given = {k: v for k, v in params.items() if not isinstance(v, UnsetType)}

    path_vals: dict[str, Any] = {}
    query_vals: dict[str, Any] = {}
    header_vals: dict[str, Any] = {}
    cookie_vals: dict[str, Any] = {}

    if locations is None:
        placeholders = set(_PATH_PLACEHOLDER.findall(path))
        for name, value in given.items():
            (path_vals if name in placeholders else query_vals)[name] = value
    else:
        path_map = locations.get("path", {})
        query_map = locations.get("query", {})
        header_map = locations.get("header", {})
        cookie_map = locations.get("cookie", {})

        unknown = []
        for name, value in given.items():
            if name in path_map:
                path_vals[name] = value
            elif name in query_map:
                query_vals[query_map[name]] = value
            elif name in header_map:
                header_vals[header_map[name]] = value
            elif name in cookie_map:
                cookie_vals[cookie_map[name]] = value
            else:
                unknown.append(name)

        if unknown:
            raise TypeError(
                f"Unknown parameter(s) {unknown!r} for {method} {path}. "
                "Request bodies use the json/data/files/content arguments."
            )

    try:
        formatted_path = path.format(**path_vals)
    except KeyError as e:
        raise TypeError(f"Missing required path parameter: {e}") from e

    return client.build_request(
        method,
        formatted_path,
        json=json,
        data=data,
        files=files,
        content=content,
        params=query_vals,
        headers=header_vals,
        cookies=cookie_vals,
    )

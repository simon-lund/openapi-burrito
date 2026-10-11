"""Loading an OpenAPI document from a path or URL."""

import logging
import re
from pathlib import Path
from typing import Any

from prance import ResolvingParser
from prance.util.resolver import RESOLVE_FILES, RESOLVE_HTTP

logger = logging.getLogger(__name__)

MIN_OPENAPI_VERSION = (3, 0, 0)


class SpecError(Exception):
    """The document could not be loaded or is not something we can generate from."""


def load(source: str | Path) -> dict[str, Any]:
    """
    Loads and validates an OpenAPI 3.x document (JSON or YAML, file or URL).

    External (file/HTTP) ``$ref``s are resolved; internal ``#/...`` refs are
    kept so that ``parse`` can preserve model identity and handle recursion.

    :raises SpecError: for Swagger 2.0 documents, with conversion advice.
    """
    try:
        parser = ResolvingParser(
            str(source),
            backend="openapi-spec-validator",
            resolve_types=RESOLVE_FILES | RESOLVE_HTTP,
        )
    except Exception as e:
        if _looks_like_swagger_2(source):
            raise SpecError(
                "This looks like a Swagger 2.0 document; openapi-burrito "
                "requires OpenAPI 3.0+. Convert it first, e.g. with "
                "swagger2openapi (npx swagger2openapi <spec>)."
            ) from e
        raise
    spec: dict[str, Any] = parser.specification

    version = str(spec.get("openapi", "0.0.0"))
    if _parse_version(version) < MIN_OPENAPI_VERSION:
        logger.warning(
            "OpenAPI version %s is below minimum %s, generated code may not work",
            version,
            ".".join(map(str, MIN_OPENAPI_VERSION)),
        )
    return spec


def _parse_version(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return (0,)


def _looks_like_swagger_2(source: str | Path) -> bool:
    """
    Best-effort sniff for a Swagger 2.0 document (top-level "swagger" key).

    Only consulted after parsing already failed, to turn prance's cryptic
    internals error into an actionable message.
    """
    try:
        path = Path(source)
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
        elif str(source).startswith(("http://", "https://")):
            import httpx

            text = httpx.get(str(source), follow_redirects=True).text
        else:
            return False
    except Exception:
        return False
    return re.search(r"[\"']swagger[\"']\s*:\s*[\"']2\.", text) is not None

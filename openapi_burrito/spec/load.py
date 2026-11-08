"""Loading an OpenAPI document from a path or URL."""

import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import ParseResult, urlunparse

from prance import BaseParser, ResolvingParser
from prance.util.resolver import RESOLVE_FILES, RESOLVE_HTTP, RefResolver

logger = logging.getLogger(__name__)

MIN_OPENAPI_VERSION = (3, 0, 0)
BACKEND = "openapi-spec-validator"


class SpecError(Exception):
    """The document could not be loaded or is not something we can generate from."""


class _FolderRefResolver(RefResolver):  # type: ignore[misc]
    """
    Resolves ``$ref``s to files inside the spec's folder, refuses all others.

    prance calls ``_skip_reference`` before it reads any ``$ref`` target, and
    offers no public hook at that point. ``TestExternalRefs`` fails if it ever
    stops calling this override.
    """

    def _skip_reference(self, base_url: ParseResult, ref_url: ParseResult) -> bool:
        # Scheme, host and path differ: the ref leaves the current document
        if ref_url[:3] != base_url[:3] and not self._in_spec_folder(ref_url):
            raise SpecError(
                f"Refusing the external $ref {urlunparse(ref_url)!r}. A spec may "
                "only reference files inside its own folder, and a spec loaded "
                "from a URL may only reference itself, because whatever a $ref "
                "reads ends up in the generated code. If you trust this spec, "
                "allow it with --allow-external-refs."
            )
        skip: bool = super()._skip_reference(base_url, ref_url)
        return skip

    def _in_spec_folder(self, url: ParseResult) -> bool:
        local = ("", "file")
        if self.parsed_url.scheme not in local or url.scheme not in local:
            return False
        # resolve() also catches symlinks that lead out of the folder
        folder = Path(self.parsed_url.path).parent.resolve()
        return Path(url.path).resolve().is_relative_to(folder)


class _FolderRefParser(BaseParser):  # type: ignore[misc]
    """``ResolvingParser``, which cannot be told to use another resolver."""

    specification: Any

    def _validate(self) -> None:
        resolver = _FolderRefResolver(
            self.specification, self.url, resolve_types=RESOLVE_FILES
        )
        resolver.resolve_references()
        self.specification = resolver.specs
        super()._validate()


def load(source: str | Path, *, allow_external_refs: bool = False) -> dict[str, Any]:
    """
    Loads and validates an OpenAPI 3.x document (JSON or YAML, file or URL).

    ``$ref``s to files inside the spec's folder are resolved; internal
    ``#/...`` refs are kept so that ``parse`` can preserve model identity and
    handle recursion.

    :param allow_external_refs: Also resolve ``$ref``s to URLs and to files
        outside the folder. What they read ends up in the generated code, so
        this is only for specs you trust.
    :raises SpecError: for Swagger 2.0 documents, with conversion advice, and
        for a ``$ref`` that is not allowed.
    """
    try:
        if allow_external_refs:
            parser = ResolvingParser(
                str(source),
                backend=BACKEND,
                resolve_types=RESOLVE_FILES | RESOLVE_HTTP,
            )
        else:
            parser = _FolderRefParser(str(source), backend=BACKEND)
    except SpecError:
        raise
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

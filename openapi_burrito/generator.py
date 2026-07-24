import logging
import re
import subprocess
import sys
import tomllib
from collections.abc import Collection
from pathlib import Path
from typing import Any, Literal

from jinja2 import Environment, FileSystemLoader
from prance import ResolvingParser
from prance.util.resolver import RESOLVE_FILES, RESOLVE_HTTP

from .parser.operation import OperationParser
from .parser.schema import SchemaParser

logger = logging.getLogger(__name__)


MIN_OPENAPI_VERSION = (3, 0, 0)

Mode = Literal["async", "sync"]

DEFAULT_MODES: tuple[Mode, ...] = ("async",)


class GenerationError(Exception):
    """Raised when generated output fails validation before being written."""


def extract_metadata(spec: dict[str, Any]) -> dict[str, str]:
    """
    Extracts and sanitizes project metadata from the OpenAPI spec
    for the pyproject.toml.

    :param spec: The OpenAPI specification as a dictionary.
    """
    info = spec.get("info", {})

    # Convert title to a valid Python package name
    # (alphanumeric and hyphens only, lowercase)
    raw_title = str(info.get("title", "generated-client"))
    project_name = re.sub(r"[^a-z0-9-]", "", raw_title.lower().replace(" ", "-"))
    project_name = re.sub(r"-+", "-", project_name).strip("-")

    # Sanitize Description (single line, no excessive whitespace)
    # Description should be one-liner without special characters
    # (e.g., tabs, newlines) for pyproject.toml
    raw_desc = str(info.get("description", "Generated Client"))
    clean_description = " ".join(raw_desc.split())

    return {
        "project_name": project_name or "generated-client",
        "description": clean_description,
        # Default to "0.1.0" as per SemVer for initial development release
        # https://semver.org/#how-should-i-deal-with-revisions-in-the-0yz-initial-development-phase
        "version": str(info.get("version", "0.1.0")),
    }


def _parse_version(version: str) -> tuple[int, ...]:
    """Parses a dotted version string into a comparable int tuple."""
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return (0,)


def _looks_like_swagger_2(spec_path: str | Path) -> bool:
    """
    Best-effort sniff for a Swagger 2.0 document (top-level "swagger" key).

    Only consulted after parsing already failed, to turn prance's cryptic
    internals error into an actionable message.
    """
    try:
        path = Path(spec_path)
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
        elif str(spec_path).startswith(("http://", "https://")):
            import httpx

            text = httpx.get(str(spec_path), follow_redirects=True).text
        else:
            return False
    except Exception:
        return False
    return re.search(r"[\"']swagger[\"']\s*:\s*[\"']2\.", text) is not None


def _validate_rendered(output_name: str, rendered: str) -> None:
    """
    Validates rendered output before it is written.

    The compile() gate turns template drift and injection into loud
    generation-time failures. Note: compile(), not ast.parse() — only the
    former catches errors like duplicate function arguments.
    """
    try:
        if output_name.endswith(".py"):
            compile(rendered, output_name, "exec")
        elif output_name.endswith(".toml"):
            tomllib.loads(rendered)
    except (SyntaxError, tomllib.TOMLDecodeError) as e:
        raise GenerationError(
            f"Generated {output_name} is invalid ({e}). "
            "This is a bug in openapi-burrito or a hostile spec — "
            "no output was written."
        ) from e


def _format_output(output_dir: Path) -> None:
    """
    Post-formats the generated code with ruff (format + import cleanup).

    Formatting failures are logged, never fatal — the code is already
    validated, just less pretty.
    """
    ruff = [sys.executable, "-m", "ruff"]
    # --isolated: ignore any ruff config found in parent directories
    commands = [
        [*ruff, "check", "--fix", "--select", "F401,I", "--isolated", "--quiet", "."],
        [*ruff, "format", "--isolated", "--quiet", "."],
    ]
    for command in commands:
        try:
            subprocess.run(
                command,
                cwd=output_dir,
                capture_output=True,
                check=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError) as e:
            logger.warning("Post-formatting step failed (%s), output is unformatted", e)
            return


def generate_sdk(
    spec_path: str | Path,
    output_dir: str | Path,
    client_modes: Collection[Mode] = DEFAULT_MODES,
) -> None:
    """
    Generates the Python SDK from the given OpenAPI input source.

    :param spec_path: Path or URL to the OpenAPI specification (JSON or YAML).
    :param output_dir: Directory where the generated client will be saved.
    :param client_modes: Which client flavors to generate: any subset of
        {"async", "sync"} (default: async only). Class names never change
        with the modes — they only control what is emitted.
    """
    output_dir = Path(output_dir)  # Ensure Path object

    modes = set(client_modes)
    if not modes or not modes <= {"async", "sync"}:
        raise GenerationError(f"Invalid client modes: {sorted(modes)!r}")

    # Resolve external (file/HTTP) refs only. Internal #/... refs are kept so
    # the parsers retain ref identity ($ref -> model name) and recursive
    # schemas work.
    try:
        parser = ResolvingParser(
            str(spec_path),
            backend="openapi-spec-validator",
            resolve_types=RESOLVE_FILES | RESOLVE_HTTP,
        )
    except Exception as e:
        if _looks_like_swagger_2(spec_path):
            raise GenerationError(
                "This looks like a Swagger 2.0 document; openapi-burrito "
                "requires OpenAPI 3.0+. Convert it first, e.g. with "
                "swagger2openapi (npx swagger2openapi <spec>)."
            ) from e
        raise
    spec = parser.specification

    metadata = extract_metadata(spec)

    logger.info(
        "Loaded spec: %s v%s",
        metadata["project_name"],
        metadata["version"],
    )

    # Check version compatibility
    openapi_version = spec.get("openapi", "0.0.0")
    if _parse_version(openapi_version) < MIN_OPENAPI_VERSION:
        logger.warning(
            "OpenAPI version %s is below minimum %s, generated code may not work",
            openapi_version,
            ".".join(map(str, MIN_OPENAPI_VERSION)),
        )

    models = SchemaParser(spec).parse()
    operations = OperationParser(spec).parse()

    logger.info("Parsed %d models, %d operations", len(models), len(operations))

    # Generate client code
    templates_dir = Path(__file__).parent / "templates"
    env = Environment(loader=FileSystemLoader(templates_dir))

    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Writing output to %s", output_dir)

    for template_name in env.list_templates():
        template = env.get_template(template_name)
        output_name = Path(template_name).stem

        logger.debug("Writing %s", output_name)

        rendered = template.render(
            metadata=metadata,
            models=models,
            operations=operations,
            async_client="async" in modes,
            sync_client="sync" in modes,
        )
        _validate_rendered(output_name, rendered)
        (output_dir / output_name).write_text(rendered, encoding="utf-8")

    _format_output(output_dir)

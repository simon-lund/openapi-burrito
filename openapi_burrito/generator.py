import logging
import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader
from prance import ResolvingParser

from .parser.operation import OperationParser
from .parser.schema import SchemaParser

logger = logging.getLogger(__name__)


MIN_OPENAPI_VERSION = "3.0.0"


def extract_metadata(spec: dict[str, Any]) -> dict[str, str]:
    """
    Extracts and sanitizes project metadata from the OpenAPI spec
    for the pyproject.toml.

    :param spec: The OpenAPI specification as a dictionary.
    """
    info = spec.get("info", {})

    # Convert title to a valid Python package name
    # (alphanumeric and hyphens only, lowercase)
    raw_title = info.get("title", "generated-client")
    project_name = re.sub(r"[^a-z0-9-]", "", raw_title.lower().replace(" ", "-"))

    # Sanitize Description (single line, no excessive whitespace)
    # Description should be one-liner without special characters
    # (e.g., tabs, newlines) for pyproject.toml
    raw_desc = info.get("description", "Generated Client")
    clean_description = " ".join(raw_desc.split())

    return {
        "project_name": project_name,
        "description": clean_description,
        # Default to "0.1.0" as per SemVer for initial development release
        # https://semver.org/#how-should-i-deal-with-revisions-in-the-0yz-initial-development-phase
        "version": info.get("version", "0.1.0"),
    }


def generate_sdk(spec_path: str | Path, output_dir: str | Path) -> None:
    """
    Generates the Python SDK from the given OpenAPI input source.

    :param spec_path: Path or URL to the OpenAPI specification (JSON or YAML).
    :param output_dir: Directory where the generated client will be saved.
    """
    output_dir = Path(output_dir)  # Ensure Path object
    parser = ResolvingParser(spec_path, backend="openapi-spec-validator")
    resolved_spec = parser.specification

    metadata = extract_metadata(resolved_spec)

    logger.info(
        "Loaded spec: %s v%s",
        metadata["project_name"],
        metadata["version"],
    )

    # Check version compatibility
    openapi_version = resolved_spec.get("openapi", "0.0.0")
    if openapi_version < MIN_OPENAPI_VERSION:
        logger.warning(
            "OpenAPI version %s is below minimum %s, generated code may not work",
            openapi_version,
            MIN_OPENAPI_VERSION,
        )

    models = SchemaParser(resolved_spec)()
    operations = OperationParser(resolved_spec)()

    logger.info("Parsed %d models, %d operations", len(models), len(operations))

    # Generate client code
    templates_dir = Path(__file__).parent / "templates"
    env = Environment(loader=FileSystemLoader(templates_dir))

    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Writing output to %s", output_dir)

    for template_name in env.list_templates():
        template = env.get_template(template_name)
        output_name = Path(template_name).stem
        file_path = output_dir / output_name

        logger.debug("Writing %s", output_name)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(
                template.render(metadata=metadata, models=models, operations=operations)
            )

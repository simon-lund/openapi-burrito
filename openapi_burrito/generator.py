"""``generate()``: load → parse → emit → write → format."""

import logging
import subprocess
import sys
from collections.abc import Collection
from pathlib import Path

from .emit import DEFAULT_MODES, Mode, emit
from .spec import load, parse

logger = logging.getLogger(__name__)


def generate(
    spec_path: str | Path,
    output_dir: str | Path,
    modes: Collection[Mode] = DEFAULT_MODES,
) -> None:
    """
    Generates a Python client package from an OpenAPI specification.

    :param spec_path: Path or URL to the OpenAPI specification (JSON or YAML).
    :param output_dir: Directory where the generated package is written.
    :param modes: Which client flavors to generate, ``"async"`` and/or
        ``"sync"`` (default: async only).
    """
    output_dir = Path(output_dir)

    api = parse(load(spec_path))
    logger.info("Loaded spec: %s v%s", api.title, api.version)
    logger.info("Parsed %d models, %d operations", len(api.models), len(api.operations))

    files = emit(api, modes)

    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Writing output to %s", output_dir)
    for name, source in files.items():
        logger.debug("Writing %s", name)
        (output_dir / name).write_text(source, encoding="utf-8")

    _format_output(output_dir)


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

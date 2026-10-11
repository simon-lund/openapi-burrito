"""``preview``: serve a spec with Swagger UI and Redoc for a look before generating."""

import json
import sys
from pathlib import Path
from typing import Any

import typer

INSTALL_HINT = """\
❌ Preview dependencies missing!
To use this feature, install the 'preview' extra:

  uv tool upgrade --with openapi-burrito[preview] openapi-burrito   (uv tool)
  pip install 'openapi-burrito[preview]'                             (pip)
  uv sync --extra preview                                            (this repo)
"""


def run_preview(input_source: str, port: int = 8000) -> None:
    """Launch a local server with Swagger UI and Redoc for the given OpenAPI spec.

    :param input_source: Path or URL to the OpenAPI specification (JSON or YAML).
    :param port: Port to run the server on (default: 8000).
    """
    try:
        import httpx
        import uvicorn
        import yaml
        from fastapi import FastAPI
        from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
        from starlette.responses import HTMLResponse
    except ImportError:
        typer.secho(INSTALL_HINT, fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=1) from None

    try:
        if input_source.startswith(("http://", "https://")):
            spec_data = httpx.get(input_source).json()
        elif input_source.endswith(".json"):
            spec_data = json.loads(Path(input_source).read_text(encoding="utf-8"))
        elif input_source.endswith((".yaml", ".yml")):
            spec_data = yaml.safe_load(Path(input_source).read_text(encoding="utf-8"))
        else:
            typer.secho(
                f"\n❌ Unsupported file format for {input_source}. Use .json or .yaml",
                fg=typer.colors.RED,
                bold=True,
            )
            raise typer.Exit(code=1)
    except Exception as e:
        typer.secho(
            f"\n❌ Failed to load spec from {input_source}: {e}",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=1) from e

    # Disable the default openapi, docs, and redoc so they don't conflict with ours
    app_ui = FastAPI(
        title="SDK Spec Preview", openapi_url=None, docs_url=None, redoc_url=None
    )

    @app_ui.get("/openapi.json", include_in_schema=False)
    async def get_spec() -> Any:
        return spec_data

    @app_ui.get("/docs", include_in_schema=False)
    async def swagger_ui() -> HTMLResponse:
        return get_swagger_ui_html(openapi_url="/openapi.json", title="Swagger UI")

    @app_ui.get("/redoc", include_in_schema=False)
    async def redoc_ui() -> HTMLResponse:
        return get_redoc_html(openapi_url="/openapi.json", title="Redoc")

    typer.secho("\n🚀 Preview Server Running!", fg=typer.colors.GREEN, bold=True)
    typer.echo("  - Swagger UI: ", nl=False)
    typer.secho(f"http://127.0.0.1:{port}/docs", fg=typer.colors.CYAN, underline=True)
    typer.echo("  - Redoc:      ", nl=False)
    typer.secho(f"http://127.0.0.1:{port}/redoc", fg=typer.colors.CYAN, underline=True)

    uvicorn.run(app_ui, host="127.0.0.1", port=port, log_level="error")


if __name__ == "__main__":
    # Allows running: python openapi_burrito/preview.py my_spec.yaml
    if len(sys.argv) < 2:
        typer.echo("Usage: python preview.py <path_or_url_to_spec>", err=True)
        sys.exit(1)

    run_preview(sys.argv[1])

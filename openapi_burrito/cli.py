import logging
from pathlib import Path

import typer

from .generator import generate_sdk

app = typer.Typer(
    help="Generate a type-safe Python client from an OpenAPI specification.",
    rich_markup_mode="rich",
    no_args_is_help=True
)


def setup_logging(verbose: bool):
    """Configures how the user sees logs based on the verbose flag."""
    if verbose:
        level = logging.DEBUG
        fmt = "%(levelname)s: %(name)s:%(lineno)d - %(message)s"
    else:
        level = logging.INFO
        fmt = "%(message)s"

    logging.basicConfig(level=level, format=fmt)


@app.command()
def generate(
        input_source: str = typer.Argument(
            ...,
            help="Path or URL to the OpenAPI specification (JSON or YAML).",
        ),
        output_dir: Path = typer.Option(
            Path("./sdk"),  # Default value
            "--output", "-o",
            help="Directory where the generated client will be saved.",
            file_okay=False,
            dir_okay=True,
            writable=True,
        ),
        verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose logging")
):
    """
    [bold]Generate[/bold] a Python client from an OpenAPI specification.
    """
    setup_logging(verbose)

    typer.secho(f"🚀 Preparing to generate client...", fg=typer.colors.CYAN)
    typer.echo(f"  - Source: {input_source}")
    typer.echo(f"  - Output: {output_dir}")

    try:
        generate_sdk(input_source, output_dir)
        typer.secho(f"\n✨ Successfully generated client in {output_dir}", fg=typer.colors.GREEN, bold=True)
    except Exception as e:
        typer.secho(f"\n❌ Error: {e}", fg=typer.colors.RED, err=True)
        if verbose:
            raise  # This will show the full stack trace if -v is used
        raise typer.Exit(code=1)


@app.command()
def preview(
        input_source: str = typer.Argument(..., help="Path or URL to the OpenAPI specification (JSON or YAML).")
):
    """
    Launch a local server with Swagger UI and Redoc.
    """
    from .preview import run_preview
    run_preview(input_source)

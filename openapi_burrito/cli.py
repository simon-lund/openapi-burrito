import logging
from enum import Enum
from pathlib import Path

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel

from . import generator
from .emit import MODES


class Mode(str, Enum):
    """Client flavor to generate. Typer needs an Enum; emit.MODES is the truth."""

    async_ = "async"
    sync = "sync"


assert {m.value for m in Mode} == set(MODES)


console = Console()


def print_security_warning() -> None:
    """Prints a framed security warning before code generation."""
    warning_text = """\
Code generators can execute malicious payloads from untrusted OpenAPI specs.

[red]\
Example: A schema named [code]"User:\\nimport os;"os.system('rm -rf /')\"[/code] could inject code.\
[/red]

This generator sanitizes inputs, but the safest approach is to review the spec yourself.

[cyan bold]Tip:[/cyan bold] Use [code]openapi-burrito preview <spec>[/code] to inspect a spec before generating.\
"""  # noqa: E501

    console.print()
    console.print(
        Panel(
            warning_text,
            title=":warning: Security Notice",
            border_style="yellow",
            width=80,
        )
    )


app = typer.Typer(
    help="Generate a type-safe Python client from an OpenAPI specification.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)


def setup_logging(verbose: bool) -> None:
    """Configures nicely formatted, colorized logging."""
    level = logging.DEBUG if verbose else logging.INFO

    # Clean output without timestamps for clarity, unless verbose
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, show_time=verbose)],
    )


@app.command()
def generate(
    spec_source: str = typer.Argument(
        ...,
        help="Path or URL to the OpenAPI specification (JSON or YAML).",
    ),
    output_dir: Path = typer.Option(
        Path("./sdk"),  # Default value
        "--output",
        "-o",
        help="Directory where the generated client will be saved.",
        file_okay=False,
        dir_okay=True,
        writable=True,
    ),
    client: list[Mode] = typer.Option(
        [Mode.async_],
        "--client",
        "-c",
        help="Client flavor(s) to generate: async (AsyncClient, default) "
        "or sync (Client). Repeat the flag to generate both "
        "(-c async -c sync).",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Enable verbose logging"
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip security confirmation prompt"
    ),
) -> None:
    """
    [bold]Generate[/bold] a Python client from an OpenAPI specification.
    """
    setup_logging(verbose)

    if not yes:
        print_security_warning()
        console.print(f"[yellow]About to generate client from:[/yellow] {spec_source}")
        if not typer.confirm("I trust this spec and want to proceed"):
            raise typer.Abort()

    console.print(":rocket: Preparing to generate client...", style="cyan")
    typer.echo(f"  - Source: {spec_source}")
    typer.echo(f"  - Output: {output_dir}")

    try:
        generator.generate(spec_source, output_dir, modes={m.value for m in client})
        console.print(
            f"\n:sparkles: Successfully generated client in {output_dir}",
            style="bold green",
        )
    except Exception as e:
        console.print(f"\n:x: Error: {e}", style="red")
        if verbose:
            raise  # This will show the full stack trace if -v is used
        raise typer.Exit(code=1) from None


@app.command()
def preview(
    input_source: str = typer.Argument(
        ..., help="Path or URL to the OpenAPI specification (JSON or YAML)."
    ),
    port: int = typer.Option(8000, "--port", "-p", help="Port to run the server on."),
) -> None:
    """
    Launch a local server with Swagger UI and Redoc.
    """
    from .preview import run_preview

    run_preview(input_source, port=port)

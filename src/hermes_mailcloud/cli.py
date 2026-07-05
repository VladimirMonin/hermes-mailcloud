"""CLI entry point for hermes-mailcloud.

Wave 0: Typer skeleton with placeholder commands.
Real implementations arrive in later waves per docs/03-development-plan.md.
"""

from __future__ import annotations

import typer

from . import __version__

app = typer.Typer(
    name="hermes-mailcloud",
    help="Agent CLI for Mail.ru Cloud — rclone-backed, JSON-first, safety-aware.",
    no_args_is_help=True,
    add_completion=False,
)


@app.command()
def version() -> None:
    """Print version and exit."""
    typer.echo(__version__)


@app.command()
def doctor(
    remote: str = typer.Option("mailru:", "--remote", help="rclone remote"),
    json_output: bool = typer.Option(False, "--json", help="machine-readable JSON"),
) -> None:
    """Diagnose rclone, remote, and basic capabilities."""
    typer.echo("doctor: not implemented yet (Wave 7)")


@app.command()
def ls(
    path: str = typer.Argument(..., help="remote path to list"),
    remote: str = typer.Option("mailru:", "--remote"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """List files and folders."""
    typer.echo("ls: not implemented yet (Wave 3)")


@app.command()
def upload(
    local: str = typer.Argument(..., help="local file path"),
    remote_path: str = typer.Argument(..., help="destination remote path"),
    remote: str = typer.Option("mailru:", "--remote"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Upload a file (private by default)."""
    typer.echo("upload: not implemented yet (Wave 3)")


@app.command()
def publish(
    local: str = typer.Argument(..., help="local file path"),
    remote_path: str = typer.Argument(..., help="destination under /Hermes/public"),
    remote: str = typer.Option("mailru:", "--remote"),
    json_output: bool = typer.Option(False, "--json"),
    yes: bool = typer.Option(False, "--yes", help="confirm publish action"),
) -> None:
    """Upload a file and create a public link."""
    typer.echo("publish: not implemented yet (Wave 4)")


@app.command()
def link(
    remote_path: str = typer.Argument(..., help="existing remote path"),
    remote: str = typer.Option("mailru:", "--remote"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Get or create a public link for an existing file."""
    typer.echo("link: not implemented yet (Wave 4)")


if __name__ == "__main__":
    app()

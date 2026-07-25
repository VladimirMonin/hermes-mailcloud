"""JSON-first CLI plumbing with explicit failure for unimplemented commands."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import typer
import typer._click as click
from typer.core import TyperGroup

from . import __version__
from .core.errors import ErrorKind, ErrorPayload
from .core.result import ResultEnvelope


class _GlobalOptionsGroup(TyperGroup):
    """Allow interspersed global options and JSON-safe Click usage failures."""

    allow_interspersed_args = True

    def main(
        self,
        args: Sequence[str] | None = None,
        prog_name: str | None = None,
        complete_var: str | None = None,
        standalone_mode: bool = True,
        windows_expand_args: bool = True,
        **extra: Any,
    ) -> Any:
        raw_args = list(args) if args is not None else None
        inspected_args = raw_args if raw_args is not None else list(sys.argv[1:])
        if standalone_mode and _json_help_requested(inspected_args):
            _emit_json_help(inspected_args)
            raise SystemExit(0)
        try:
            result = super().main(
                args=raw_args,
                prog_name=prog_name,
                complete_var=complete_var,
                standalone_mode=False,
                windows_expand_args=windows_expand_args,
                **extra,
            )
        except click.ClickException as error:
            if not standalone_mode:
                raise
            if _json_requested(inspected_args):
                _emit_json_usage_error(inspected_args)
                exit_code = ErrorPayload(
                    ErrorKind.INVALID_ARGUMENTS, "invalid command arguments"
                ).exit_code
                raise SystemExit(exit_code) from None
            error.show()
            raise SystemExit(error.exit_code) from None

        if standalone_mode and isinstance(result, int):
            raise SystemExit(result)
        return result


@dataclass(frozen=True, slots=True)
class CliRuntimeOptions:
    """Global options parsed once and retained for later command implementations."""

    profile: str
    remote: str | None
    config_path: Path | None
    json_output: bool
    pretty: bool
    quiet: bool
    debug: bool
    trace_id: str | None
    dry_run: bool
    yes: bool
    timeout_seconds: int | None
    retries: int
    no_color: bool


app = typer.Typer(
    cls=_GlobalOptionsGroup,
    name="hermes-mailcloud",
    help="Agent CLI for Mail.ru Cloud — rclone-backed, JSON-first, safety-aware.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def main(
    context: typer.Context,
    profile: str = typer.Option("default", "--profile", help="configuration profile"),
    remote: str | None = typer.Option(None, "--remote", help="rclone remote override"),
    config_path: Annotated[
        Path | None, typer.Option("--config", help="configuration file override")
    ] = None,
    json_output: bool = typer.Option(False, "--json", help="emit one JSON result envelope"),
    pretty: bool = typer.Option(False, "--pretty", help="indent JSON output"),
    quiet: bool = typer.Option(False, "--quiet", help="suppress non-essential human output"),
    debug: bool = typer.Option(False, "--debug", help="enable safe diagnostics"),
    trace_id: str | None = typer.Option(None, "--trace-id", help="operation correlation id"),
    dry_run: bool = typer.Option(False, "--dry-run", help="validate and plan without execution"),
    yes: bool = typer.Option(False, "--yes", help="confirm a dangerous operation"),
    timeout_seconds: int | None = typer.Option(None, "--timeout", min=1, help="rclone timeout"),
    retries: int = typer.Option(0, "--retries", min=0, help="safe read-only retries"),
    no_color: bool = typer.Option(False, "--no-color", help="disable ANSI color"),
) -> None:
    """Parse all v0.1 global flags without starting a backend process."""
    context.obj = CliRuntimeOptions(
        profile=profile,
        remote=remote,
        config_path=config_path,
        json_output=json_output,
        pretty=pretty,
        quiet=quiet,
        debug=debug,
        trace_id=trace_id,
        dry_run=dry_run,
        yes=yes,
        timeout_seconds=timeout_seconds,
        retries=retries,
        no_color=no_color,
    )


@app.command()
def version(context: typer.Context) -> None:
    """Print the installed package version."""
    options = _options(context)
    if options.json_output:
        _emit(
            ResultEnvelope.success(
                "version",
                {"version": __version__},
                profile=options.profile,
                trace_id=options.trace_id,
            ),
            options,
        )
        return
    typer.echo(__version__)


@app.command()
def doctor(context: typer.Context) -> None:
    """Diagnose rclone, remote, and basic capabilities."""
    _placeholder(context, "doctor")


@app.command()
def ls(context: typer.Context, path: str = typer.Argument(..., help="remote path to list")) -> None:
    """List files and folders."""
    del path
    _placeholder(context, "ls")


@app.command()
def stat(
    context: typer.Context,
    remote_path: str = typer.Argument(..., help="remote path to inspect"),
) -> None:
    """Inspect one remote file or folder."""
    del remote_path
    _placeholder(context, "stat")


@app.command()
def mkdir(
    context: typer.Context,
    remote_path: str = typer.Argument(..., help="remote directory path"),
) -> None:
    """Create a remote directory."""
    del remote_path
    _placeholder(context, "mkdir")


@app.command()
def upload(
    context: typer.Context,
    local: str = typer.Argument(..., help="local file path"),
    remote_path: str = typer.Argument(..., help="destination remote path"),
) -> None:
    """Upload a file (private by default)."""
    del local, remote_path
    _placeholder(context, "upload")


@app.command()
def download(
    context: typer.Context,
    remote_path: str = typer.Argument(..., help="source remote file path"),
    local: str = typer.Argument(..., help="destination local file path"),
) -> None:
    """Download a remote file."""
    del remote_path, local
    _placeholder(context, "download")


@app.command()
def mv(
    context: typer.Context,
    source_path: str = typer.Argument(..., help="source remote path"),
    target_path: str = typer.Argument(..., help="destination remote path"),
) -> None:
    """Move or rename a remote object."""
    del source_path, target_path
    _placeholder(context, "mv")


@app.command()
def cp(
    context: typer.Context,
    source_path: str = typer.Argument(..., help="source remote path"),
    target_path: str = typer.Argument(..., help="destination remote path"),
) -> None:
    """Copy a remote object."""
    del source_path, target_path
    _placeholder(context, "cp")


@app.command()
def rm(
    context: typer.Context,
    remote_path: str = typer.Argument(..., help="remote file or directory path"),
) -> None:
    """Delete a remote file or directory."""
    del remote_path
    _placeholder(context, "rm")


@app.command()
def publish(
    context: typer.Context,
    local: str = typer.Argument(..., help="local file path"),
    remote_path: str = typer.Argument(..., help="destination under /Hermes/public"),
) -> None:
    """Upload a file and create a public link."""
    del local, remote_path
    _placeholder(context, "publish")


@app.command()
def link(
    context: typer.Context,
    remote_path: str = typer.Argument(..., help="existing remote path"),
) -> None:
    """Get or create a public link for an existing file."""
    del remote_path
    _placeholder(context, "link")


@app.command()
def batch(
    context: typer.Context,
    plan_path: Annotated[Path, typer.Argument(help="JSON batch plan path")],
) -> None:
    """Run a JSON plan of cloud operations."""
    del plan_path
    _placeholder(context, "batch")


def _placeholder(context: typer.Context, operation: str) -> None:
    options = _options(context)
    error = ErrorPayload(
        ErrorKind.BACKEND_UNSUPPORTED,
        f"{operation} is not implemented in this build",
    )
    envelope = ResultEnvelope.failure(
        operation,
        error,
        profile=options.profile,
        remote=options.remote,
        trace_id=options.trace_id,
    )
    _emit(envelope, options)
    raise typer.Exit(error.exit_code)


def _options(context: typer.Context) -> CliRuntimeOptions:
    options = context.find_root().obj
    if not isinstance(options, CliRuntimeOptions):
        raise RuntimeError("global CLI options were not initialized")
    return options


def _emit(envelope: ResultEnvelope, options: CliRuntimeOptions) -> None:
    if options.json_output:
        typer.echo(envelope.to_json(pretty=options.pretty))
        return
    message = envelope.error.message if envelope.error is not None else _human_success(envelope)
    typer.echo(message, err=envelope.error is not None)


def _json_requested(args: Sequence[str]) -> bool:
    return "--json" in _option_arguments(args)


def _json_help_requested(args: Sequence[str]) -> bool:
    option_arguments = _option_arguments(args)
    return "--json" in option_arguments and "--help" in option_arguments


def _option_arguments(args: Sequence[str]) -> Sequence[str]:
    try:
        return args[: args.index("--")]
    except ValueError:
        return args


def _command_name(args: Sequence[str]) -> str:
    return next((arg for arg in _option_arguments(args) if arg in _COMMAND_NAMES), "cli")


def _emit_json_help(args: Sequence[str]) -> None:
    envelope = ResultEnvelope.success(
        "cli", {"help": {"command": _command_name(args), "format": "json"}}
    )
    typer.echo(envelope.to_json(pretty="--pretty" in _option_arguments(args)))


def _emit_json_usage_error(args: Sequence[str]) -> None:
    error = ErrorPayload(ErrorKind.INVALID_ARGUMENTS, "invalid command arguments")
    operation = _command_name(args)
    typer.echo(ResultEnvelope.failure(operation, error).to_json(pretty="--pretty" in args))


_COMMAND_NAMES = frozenset(
    {
        "version",
        "doctor",
        "ls",
        "stat",
        "mkdir",
        "upload",
        "download",
        "mv",
        "cp",
        "rm",
        "publish",
        "link",
        "batch",
    }
)


def _human_success(envelope: ResultEnvelope) -> str:
    result: dict[str, Any] = dict(envelope.result or {})
    return str(result.get("version", "command completed"))


if __name__ == "__main__":
    app()

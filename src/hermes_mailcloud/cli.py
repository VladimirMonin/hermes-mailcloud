"""Thin JSON-first input/output adapter for the independent application API."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import typer
import typer._click as click
from typer.core import TyperGroup

from .application import CallOptions, ConfigOverrides, MailCloudApplication
from .core.errors import ErrorKind, ErrorPayload
from .core.result import ResultEnvelope


class _GlobalOptionsGroup(TyperGroup):
    """Allow interspersed global options and JSON-safe Click usage failures."""

    allow_interspersed_args = False

    def main(
        self,
        args: Sequence[str] | None = None,
        prog_name: str | None = None,
        complete_var: str | None = None,
        standalone_mode: bool = True,
        windows_expand_args: bool = True,
        **extra: Any,
    ) -> Any:
        raw_args = list(args) if args is not None else list(sys.argv[1:])
        inspected_args = raw_args
        if standalone_mode and _json_help_requested(inspected_args):
            _emit_json_help(inspected_args)
            raise SystemExit(0)
        try:
            result = super().main(
                args=_normalize_global_options(raw_args),
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

    profile: str | None
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
    retries: int | None
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
    profile: str | None = typer.Option(
        None, "--profile", help="configuration profile (HMC_PROFILE, otherwise default)"
    ),
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
    retries: int | None = typer.Option(None, "--retries", min=0, help="safe read-only retries"),
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
    _emit_application_result(
        MailCloudApplication().version(options=_call_options(options)), options
    )


@app.command()
def setup(
    context: typer.Context,
    archive: Annotated[
        Path | None,
        typer.Option(
            "--archive", help="use a local official archive with the packaged SHA-256 pin"
        ),
    ] = None,
) -> None:
    """Explicitly prepare user-scoped rclone only; never configure a cloud account."""
    options = _options(context)
    _emit_application_result(
        MailCloudApplication().setup(archive=archive, options=_call_options(options)), options
    )


@app.command()
def doctor(
    context: typer.Context,
    live: bool = typer.Option(False, "--live", help="run generated /TEST probes (requires --yes)"),
) -> None:
    """Diagnose rclone and remote readiness without cloud mutation by default."""
    options = _options(context)
    _emit_application_result(
        MailCloudApplication().doctor(live=live, options=_call_options(options)), options
    )


@app.command()
def ls(
    context: typer.Context,
    path: str = typer.Argument(..., help="remote path to list"),
    recursive: bool = typer.Option(False, "--recursive", help="list descendants recursively"),
    files_only: bool = typer.Option(False, "--files-only", help="list files only"),
    dirs_only: bool = typer.Option(False, "--dirs-only", help="list directories only"),
) -> None:
    """List files and folders."""
    options = _options(context)
    _emit_application_result(
        MailCloudApplication().ls(
            path,
            recursive=recursive,
            files_only=files_only,
            dirs_only=dirs_only,
            options=_call_options(options),
        ),
        options,
    )


@app.command()
def stat(
    context: typer.Context,
    remote_path: str = typer.Argument(..., help="remote path to inspect"),
) -> None:
    """Inspect one remote file or folder."""
    options = _options(context)
    _emit_application_result(
        MailCloudApplication().stat(remote_path, options=_call_options(options)), options
    )


@app.command()
def mkdir(
    context: typer.Context,
    remote_path: str = typer.Argument(..., help="remote directory path"),
) -> None:
    """Create a remote directory."""
    options = _options(context)
    _emit_application_result(
        MailCloudApplication().mkdir(remote_path, options=_call_options(options)), options
    )


@app.command()
def upload(
    context: typer.Context,
    local: str = typer.Argument(..., help="local file path"),
    remote_path: str = typer.Argument(..., help="destination remote path"),
    overwrite: str | None = typer.Option(
        None, "--overwrite", help="never, always, or if-newer (profile default when omitted)"
    ),
) -> None:
    """Upload a file (private by default)."""
    options = _options(context)
    _emit_application_result(
        MailCloudApplication().upload(
            local, remote_path, overwrite=overwrite, options=_call_options(options)
        ),
        options,
    )


@app.command()
def download(
    context: typer.Context,
    remote_path: str = typer.Argument(..., help="source remote file path"),
    local: str = typer.Argument(..., help="destination local file path"),
    overwrite: str | None = typer.Option(
        None, "--overwrite", help="never, always, or if-newer (profile default when omitted)"
    ),
) -> None:
    """Download a remote file."""
    options = _options(context)
    _emit_application_result(
        MailCloudApplication().download(
            remote_path, local, overwrite=overwrite, options=_call_options(options)
        ),
        options,
    )


@app.command()
def mv(
    context: typer.Context,
    source_path: str = typer.Argument(..., help="source remote path"),
    target_path: str = typer.Argument(..., help="destination remote path"),
    overwrite: str | None = typer.Option(
        None, "--overwrite", help="never, always, or if-newer (profile default when omitted)"
    ),
) -> None:
    """Move or rename a remote object."""
    options = _options(context)
    _emit_application_result(
        MailCloudApplication().mv(
            source_path, target_path, overwrite=overwrite, options=_call_options(options)
        ),
        options,
    )


@app.command()
def cp(
    context: typer.Context,
    source_path: str = typer.Argument(..., help="source remote path"),
    target_path: str = typer.Argument(..., help="destination remote path"),
    overwrite: str | None = typer.Option(
        None, "--overwrite", help="never, always, or if-newer (profile default when omitted)"
    ),
) -> None:
    """Copy a remote object."""
    options = _options(context)
    _emit_application_result(
        MailCloudApplication().cp(
            source_path, target_path, overwrite=overwrite, options=_call_options(options)
        ),
        options,
    )


@app.command()
def rm(
    context: typer.Context,
    remote_path: str = typer.Argument(..., help="remote file or directory path"),
    recursive: bool = typer.Option(False, "--recursive", help="delete a path and all descendants"),
) -> None:
    """Permanently delete one file, or a path and descendants with --recursive."""
    options = _options(context)
    _emit_application_result(
        MailCloudApplication().rm(remote_path, recursive=recursive, options=_call_options(options)),
        options,
    )


@app.command()
def publish(
    context: typer.Context,
    local: str = typer.Argument(..., help="local file path"),
    remote_path: str = typer.Argument(..., help="destination under /Hermes/public"),
    overwrite: str | None = typer.Option(
        None, "--overwrite", help="never, always, or if-newer (profile default when omitted)"
    ),
) -> None:
    """Upload a file and create a public link."""
    options = _options(context)
    _emit_application_result(
        MailCloudApplication().publish(
            local, remote_path, overwrite=overwrite, options=_call_options(options)
        ),
        options,
    )


@app.command()
def link(
    context: typer.Context,
    remote_path: str = typer.Argument(..., help="existing remote path"),
) -> None:
    """Get or create a public link for an existing file."""
    options = _options(context)
    _emit_application_result(
        MailCloudApplication().link(remote_path, options=_call_options(options)), options
    )


@app.command()
def batch(
    context: typer.Context,
    plan_path: Annotated[Path, typer.Argument(help="JSON batch plan path")],
) -> None:
    """Run a JSON plan of cloud operations."""
    options = _options(context)
    _emit_application_result(
        MailCloudApplication().batch_file(plan_path, options=_call_options(options)), options
    )


def _call_options(options: CliRuntimeOptions) -> CallOptions:
    """Translate parser values only; application owns resolution and defaults."""
    return CallOptions(
        config=ConfigOverrides(
            profile=options.profile, remote=options.remote, config_path=options.config_path
        ),
        trace_id=options.trace_id,
        dry_run=options.dry_run,
        yes=options.yes,
        timeout_seconds=options.timeout_seconds,
        retries=options.retries,
    )


def _emit_application_result(envelope: ResultEnvelope, options: CliRuntimeOptions) -> None:
    _emit(envelope, options)
    if envelope.exit_code:
        raise typer.Exit(envelope.exit_code)


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


_GLOBAL_FLAGS = frozenset(
    {"--json", "--pretty", "--quiet", "--debug", "--dry-run", "--yes", "--no-color"}
)
_GLOBAL_VALUE_OPTIONS = frozenset(
    {"--profile", "--remote", "--config", "--trace-id", "--timeout", "--retries"}
)


def _normalize_global_options(args: Sequence[str]) -> list[str]:
    """Move recognized global options ahead of a command without stealing command options."""
    global_options: list[str] = []
    command_arguments: list[str] = []
    index = 0
    while index < len(args):
        argument = args[index]
        if argument == "--":
            command_arguments.extend(args[index:])
            break
        option_name = argument.split("=", 1)[0]
        if option_name in _GLOBAL_FLAGS:
            global_options.append(argument)
        elif option_name in _GLOBAL_VALUE_OPTIONS:
            global_options.append(argument)
            if "=" not in argument and index + 1 < len(args):
                index += 1
                global_options.append(args[index])
        else:
            command_arguments.append(argument)
        index += 1
    return [*global_options, *command_arguments]


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
        "setup",
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
    if envelope.operation == "setup":
        return (
            f"rclone setup: {result['status']} ({result['source']}, "
            f"{result['version'] or 'not probed'}); cloud configuration unchanged"
        )
    return str(result.get("version", "command completed"))


if __name__ == "__main__":
    app()

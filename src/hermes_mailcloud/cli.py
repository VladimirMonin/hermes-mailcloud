"""JSON-first CLI plumbing with explicit failure for unimplemented commands."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import typer
import typer._click as click
from typer.core import TyperGroup

from . import __version__
from .batch import BatchCommands, parse_batch_file
from .commands.mkdir import MkdirCommand
from .commands.move_copy import MoveCopyCommands
from .commands.public import PublicCommands
from .commands.read import ReadCommands
from .commands.remove import RemoveCommand
from .commands.transfer import TransferCommands
from .config import CliConfigOverrides, ResolvedConfig, resolve_config
from .core.errors import ErrorKind, ErrorPayload, MailCloudError
from .core.result import ResultEnvelope
from .doctor import DoctorCommands
from .rclone.install import prepare_rclone
from .rclone.runner import RcloneRunner


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
    _run_rclone_command(
        context,
        "setup",
        lambda config, _runner: prepare_rclone(
            config.rclone_path,
            explicit=config.rclone_path_explicit,
            archive=archive,
            dry_run=options.dry_run,
            timeout_seconds=_effective_timeout(options, config),
        ),
    )


@app.command()
def doctor(
    context: typer.Context,
    live: bool = typer.Option(False, "--live", help="run generated /TEST probes (requires --yes)"),
) -> None:
    """Diagnose rclone and remote readiness without cloud mutation by default."""
    _run_doctor_command(context, live=live)


@app.command()
def ls(
    context: typer.Context,
    path: str = typer.Argument(..., help="remote path to list"),
    recursive: bool = typer.Option(False, "--recursive", help="list descendants recursively"),
    files_only: bool = typer.Option(False, "--files-only", help="list files only"),
    dirs_only: bool = typer.Option(False, "--dirs-only", help="list directories only"),
) -> None:
    """List files and folders."""
    _run_rclone_command(
        context,
        "ls",
        lambda config, backend: ReadCommands(
            backend,
            config,
            timeout_seconds=_effective_timeout(_options(context), config),
            retries=_effective_read_retries(_options(context), config),
        ).ls(path, recursive=recursive, files_only=files_only, dirs_only=dirs_only),
    )


@app.command()
def stat(
    context: typer.Context,
    remote_path: str = typer.Argument(..., help="remote path to inspect"),
) -> None:
    """Inspect one remote file or folder."""
    _run_rclone_command(
        context,
        "stat",
        lambda config, backend: ReadCommands(
            backend,
            config,
            timeout_seconds=_effective_timeout(_options(context), config),
            retries=_effective_read_retries(_options(context), config),
        ).stat(remote_path),
    )


@app.command()
def mkdir(
    context: typer.Context,
    remote_path: str = typer.Argument(..., help="remote directory path"),
) -> None:
    """Create a remote directory."""
    options = _options(context)
    _run_rclone_command(
        context,
        "mkdir",
        lambda config, backend: MkdirCommand(
            backend,
            config,
            timeout_seconds=_effective_timeout(options, config),
        ).run(
            remote_path,
            dry_run=options.dry_run,
            yes=options.yes,
            retries=_effective_write_retries(options),
        ),
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
    _run_rclone_command(
        context,
        "upload",
        lambda config, backend: TransferCommands(
            backend, config, timeout_seconds=_effective_timeout(options, config)
        ).upload(
            local,
            remote_path,
            overwrite=overwrite,
            dry_run=options.dry_run,
            retries=_effective_write_retries(options),
        ),
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
    _run_rclone_command(
        context,
        "download",
        lambda config, backend: TransferCommands(
            backend, config, timeout_seconds=_effective_timeout(options, config)
        ).download(
            remote_path,
            local,
            overwrite=overwrite,
            dry_run=options.dry_run,
            retries=_effective_write_retries(options),
        ),
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
    _run_rclone_command(
        context,
        "mv",
        lambda config, backend: MoveCopyCommands(
            backend, config, timeout_seconds=_effective_timeout(options, config)
        ).move(
            source_path,
            target_path,
            overwrite=overwrite,
            dry_run=options.dry_run,
            retries=_effective_write_retries(options),
        ),
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
    _run_rclone_command(
        context,
        "cp",
        lambda config, backend: MoveCopyCommands(
            backend, config, timeout_seconds=_effective_timeout(options, config)
        ).copy(
            source_path,
            target_path,
            overwrite=overwrite,
            dry_run=options.dry_run,
            retries=_effective_write_retries(options),
        ),
    )


@app.command()
def rm(
    context: typer.Context,
    remote_path: str = typer.Argument(..., help="remote file or directory path"),
    recursive: bool = typer.Option(False, "--recursive", help="delete a path and all descendants"),
) -> None:
    """Permanently delete one file, or a path and descendants with --recursive."""
    options = _options(context)
    _run_rclone_command(
        context,
        "rm",
        lambda config, backend: RemoveCommand(
            backend, config, timeout_seconds=_effective_timeout(options, config)
        ).run(
            remote_path,
            recursive=recursive,
            dry_run=options.dry_run,
            yes=options.yes,
            retries=_effective_write_retries(options),
        ),
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
    _run_rclone_command(
        context,
        "publish",
        lambda config, backend: PublicCommands(
            backend, config, timeout_seconds=_effective_timeout(options, config)
        ).publish(
            local,
            remote_path,
            overwrite=overwrite,
            dry_run=options.dry_run,
            yes=options.yes,
            retries=_effective_write_retries(options),
        ),
    )


@app.command()
def link(
    context: typer.Context,
    remote_path: str = typer.Argument(..., help="existing remote path"),
) -> None:
    """Get or create a public link for an existing file."""
    options = _options(context)
    _run_rclone_command(
        context,
        "link",
        lambda config, backend: PublicCommands(
            backend, config, timeout_seconds=_effective_timeout(options, config)
        ).link(
            remote_path,
            dry_run=options.dry_run,
            retries=_effective_write_retries(options),
        ),
    )


@app.command()
def batch(
    context: typer.Context,
    plan_path: Annotated[Path, typer.Argument(help="JSON batch plan path")],
) -> None:
    """Run a JSON plan of cloud operations."""
    _run_batch_command(context, plan_path)


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


def _run_rclone_command(
    context: typer.Context,
    operation: str,
    action: Callable[[ResolvedConfig, RcloneRunner], dict[str, object]],
) -> None:
    """Resolve non-secret configuration, execute one adapter, and emit one safe envelope."""
    options = _options(context)
    config: ResolvedConfig | None = None
    try:
        config = resolve_config(
            CliConfigOverrides(
                profile=options.profile,
                remote=options.remote,
                config_path=options.config_path,
            )
        )
        result = action(config, RcloneRunner(config.rclone_path))
    except MailCloudError as exc:
        envelope = ResultEnvelope.failure(
            operation,
            exc.error,
            profile=config.profile if config is not None else options.profile,
            remote=config.remote if config is not None else options.remote,
            trace_id=options.trace_id,
        )
    else:
        envelope = ResultEnvelope.success(
            operation,
            result,
            profile=config.profile,
            remote=config.remote,
            trace_id=options.trace_id,
        )
    _emit(envelope, options)
    if not envelope.ok:
        raise typer.Exit(envelope.exit_code)


def _run_doctor_command(context: typer.Context, *, live: bool) -> None:
    """Emit one safe diagnostic report; live probes require both opt-in and confirmation."""
    options = _options(context)
    config: ResolvedConfig | None = None
    try:
        if live and not options.yes:
            raise MailCloudError(
                ErrorPayload(
                    ErrorKind.CONFIRMATION_REQUIRED,
                    "doctor --live requires --yes before it can create generated /TEST objects",
                )
            )
        config = resolve_config(
            CliConfigOverrides(
                profile=options.profile,
                remote=options.remote,
                config_path=options.config_path,
            )
        )
        commands = DoctorCommands(
            RcloneRunner(config.rclone_path),
            config,
            timeout_seconds=_effective_timeout(options, config),
            retries=_effective_read_retries(options, config),
        )
        report = commands.live() if live else commands.read_only()
    except MailCloudError as exc:
        envelope = ResultEnvelope.failure(
            "doctor",
            exc.error,
            profile=config.profile if config is not None else options.profile,
            remote=config.remote if config is not None else options.remote,
            trace_id=options.trace_id,
        )
    else:
        envelope = ResultEnvelope.success(
            "doctor",
            report.result,
            profile=config.profile,
            remote=config.remote,
            trace_id=options.trace_id,
            warnings=report.warnings,
        )
    _emit(envelope, options)
    if not envelope.ok:
        raise typer.Exit(envelope.exit_code)


def _run_batch_command(context: typer.Context, plan_path: Path) -> None:
    """Load a static plan before configuration, then emit a completed or partial envelope."""
    options = _options(context)
    config: ResolvedConfig | None = None
    try:
        plan = parse_batch_file(plan_path)
        config = resolve_config(
            CliConfigOverrides(
                profile=options.profile,
                remote=options.remote,
                config_path=options.config_path,
            )
        )
        execution = BatchCommands(
            RcloneRunner(config.rclone_path),
            config,
            timeout_seconds=_effective_timeout(options, config),
            read_retries=_effective_read_retries(options, config),
        ).run(
            plan,
            dry_run=options.dry_run,
            yes=options.yes,
            explicit_retries=options.retries,
        )
    except MailCloudError as exc:
        envelope = ResultEnvelope.failure(
            "batch",
            exc.error,
            profile=config.profile if config is not None else options.profile,
            remote=config.remote if config is not None else options.remote,
            trace_id=options.trace_id,
        )
    else:
        metadata = {
            "profile": config.profile,
            "remote": config.remote,
            "trace_id": options.trace_id,
        }
        envelope = (
            ResultEnvelope.batch_partial(execution.items, **metadata)
            if execution.is_partial
            else ResultEnvelope.success("batch", execution.result, **metadata)
        )
    _emit(envelope, options)
    if not envelope.ok:
        raise typer.Exit(envelope.exit_code)


def _effective_timeout(options: CliRuntimeOptions, config: ResolvedConfig) -> int:
    """Use the explicit CLI timeout when present, otherwise the validated profile value."""
    if options.timeout_seconds is not None:
        return options.timeout_seconds
    return config.timeout_seconds


def _effective_read_retries(options: CliRuntimeOptions, config: ResolvedConfig) -> int:
    """Use an explicit retry budget for reads, otherwise the profile's safe-read budget."""
    return options.retries if options.retries is not None else config.retries


def _effective_write_retries(options: CliRuntimeOptions) -> int:
    """Ignore profile read retries, but validate an explicit write retry request fail-closed."""
    return options.retries if options.retries is not None else 0


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

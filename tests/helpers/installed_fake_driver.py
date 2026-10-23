"""Standalone test-only argv driver; copy it outside the checkout before execution.

Only the external executable argv is injected at application composition and,
temporarily, the legacy CLI seam. All owners remain the installed wheel's bytes.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import importlib.abc
import importlib.metadata
import importlib.util
import io
import json
import os
import sys
from pathlib import Path

PUBLIC_URL = "https://cloud.mail.ru/public/installed-wheel-synthetic-capability/path"
DIAGNOSTIC = "installed-backend-private-sentinel"
_API_COMPONENTS = (
    "hermes_mailcloud",
    "hermes_mailcloud.application",
    "hermes_mailcloud.application.contracts",
    "hermes_mailcloud.application.validation",
    "hermes_mailcloud.application.composition",
    "hermes_mailcloud.application.service",
    "hermes_mailcloud.config",
    "hermes_mailcloud.core.errors",
    "hermes_mailcloud.core.result",
    "hermes_mailcloud.output",
    "hermes_mailcloud.commands.read",
    "hermes_mailcloud.rclone.runner",
    "hermes_mailcloud.commands.public",
    "hermes_mailcloud.commands.transfer",
    "hermes_mailcloud.commands.mkdir",
    "hermes_mailcloud.commands.move_copy",
    "hermes_mailcloud.commands.remove",
    "hermes_mailcloud.journal",
)
_COMPONENTS = (*_API_COMPONENTS, "hermes_mailcloud.cli", "hermes_mailcloud.batch")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def installed_provenance(control: dict, *, api_only: bool = False) -> dict:
    require(
        bool(sys.flags.isolated) and bool(sys.flags.utf8_mode), "runtime must be isolated UTF-8"
    )
    prefix = Path(control["prefix"]).resolve()
    checkout = Path(control["checkout"]).resolve()
    require(Path(sys.prefix).resolve() == prefix, "wrong runtime prefix")
    require(not prefix.is_relative_to(checkout), "runtime is inside the checkout")
    require(not Path.cwd().resolve().is_relative_to(checkout), "runtime cwd is in checkout")
    require(not Path(__file__).resolve().is_relative_to(checkout), "driver was not copied out")
    require(
        "PYTHONPATH" not in os.environ and "PYTHONHOME" not in os.environ,
        "Python path environment was inherited",
    )
    require(
        not any(Path(value).resolve().is_relative_to(checkout) for value in sys.path if value),
        "checkout is on the runtime import path",
    )
    for name in ("pytest", "ruff", "jsonschema", "coverage"):
        require(importlib.util.find_spec(name) is None, "development package leaked into runtime")
    selected = _API_COMPONENTS if api_only else _COMPONENTS
    modules = [importlib.import_module(name) for name in selected]
    platform_name = "journal_windows" if os.name == "nt" else "journal_posix"
    modules.append(importlib.import_module("hermes_mailcloud._platform." + platform_name))
    if os.name == "nt":
        modules.append(importlib.import_module("hermes_mailcloud.rclone._windows_process"))
    package = modules[0]
    distribution = importlib.metadata.distribution("hermes-mailcloud")
    version = distribution.version
    require(version == control["version"] == package.__version__, "installed version mismatch")
    direct = distribution.read_text("direct_url.json")
    if direct:
        require(not json.loads(direct).get("dir_info", {}).get("editable"), "editable runtime")
    package_root = Path(package.__file__).resolve().parent
    require(package_root.is_relative_to(prefix), "package imported from outside runtime")
    loaded = {}
    for name, module in list(sys.modules.items()):
        if not name.startswith("hermes_mailcloud") or not getattr(module, "__file__", None):
            continue
        path = Path(module.__file__).resolve()
        require(path.is_relative_to(package_root), "component is outside installed package")
        relative = path.relative_to(package_root.parent).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        require(control["sources"].get(relative) == digest, "component is not the wheel's bytes")
        loaded[name] = {"path": str(path), "wheel_path": relative, "sha256": digest}
    application = importlib.import_module("hermes_mailcloud.application")
    service = importlib.import_module("hermes_mailcloud.application.service")
    composition = importlib.import_module("hermes_mailcloud.application.composition")
    require(application.MailCloudApplication is service.MailCloudApplication, "API substitution")
    require(
        service.ReadCommands
        is importlib.import_module("hermes_mailcloud.commands.read").ReadCommands,
        "application read-service substitution",
    )
    require(
        composition.RcloneRunner
        is importlib.import_module("hermes_mailcloud.rclone.runner").RcloneRunner,
        "application runner substitution",
    )
    for name, module in (
        ("PublicCommands", "hermes_mailcloud.commands.public"),
        ("TransferCommands", "hermes_mailcloud.commands.transfer"),
        ("MkdirCommand", "hermes_mailcloud.commands.mkdir"),
        ("MoveCopyCommands", "hermes_mailcloud.commands.move_copy"),
        ("RemoveCommand", "hermes_mailcloud.commands.remove"),
    ):
        require(
            getattr(service, name) is getattr(importlib.import_module(module), name),
            "application write-service substitution",
        )
    journal = importlib.import_module("hermes_mailcloud.journal")
    require(
        importlib.import_module("hermes_mailcloud.commands.public").LinkJournal
        is journal.LinkJournal,
        "application journal substitution",
    )
    if not api_only:
        cli = importlib.import_module("hermes_mailcloud.cli")
        require(
            cli.MailCloudApplication is service.MailCloudApplication, "CLI application substitution"
        )
        for name, module in (("BatchCommands", "hermes_mailcloud.batch"),):
            require(
                getattr(cli, name) is getattr(importlib.import_module(module), name),
                "legacy CLI component substitution",
            )
        journal = importlib.import_module("hermes_mailcloud.journal")
        for module in ("hermes_mailcloud.commands.public", "hermes_mailcloud.batch"):
            require(
                importlib.import_module(module).LinkJournal is journal.LinkJournal,
                "journal component substitution",
            )
    installed = {
        item.metadata["Name"].lower().replace("_", "-"): item.version
        for item in importlib.metadata.distributions()
    }
    require(("pywin32" in installed) == (os.name == "nt"), "Windows dependency marker mismatch")
    if os.name == "nt":
        import win32api
        import win32con
        import win32security

        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
        try:
            security = {
                "elevated": bool(
                    win32security.GetTokenInformation(token, win32security.TokenElevation)
                ),
                "elevation_type": win32security.GetTokenInformation(
                    token, win32security.TokenElevationType
                ),
                "ordinary_user_qualification": False,
            }
        finally:
            token.Close()
    else:
        security = {
            "uid": os.geteuid(),
            "native_cwd_filesystem": Path.cwd().stat().st_dev != checkout.stat().st_dev,
        }
    return {
        "prefix": str(prefix),
        "executable": sys.executable,
        "security_context": security,
        "cwd": str(Path.cwd()),
        "python": sys.version,
        "version": version,
        "loaded_components": loaded,
        "installed": installed,
        "pythonpath_present": False,
        "development_packages_present": False,
        "component_substitution": False,
        "isolated": bool(sys.flags.isolated),
        "utf8_mode": bool(sys.flags.utf8_mode),
    }


def backend(control: dict, arguments: list[str]) -> int:
    with Path(control["log"]).open("a", encoding="utf-8") as output:
        output.write(json.dumps(arguments, ensure_ascii=False) + "\n")
    if control.get("failure_target") in arguments:
        sys.stderr.write("network is unreachable " + DIAGNOSTIC + " " + PUBLIC_URL)
        return 1
    if not arguments:
        return 97
    command, *values = arguments
    if command == "lsjson":
        item = {
            "Path": "report.txt",
            "Name": "report.txt",
            "IsDir": False,
            "Size": 16,
            "ModTime": "2026-07-25T01:02:03Z",
        }
        print(json.dumps(item if "--stat" in values else [item]))
    elif command == "copyto":
        if len(values) >= 2 and Path(values[1]).is_absolute():
            Path(values[1]).write_bytes(b"downloaded-wheel")
    elif command == "link":
        print(PUBLIC_URL)
    elif command not in {"mkdir", "moveto", "deletefile", "purge"}:
        return 97
    return 0


def executable_runner(control_path: Path, **kwargs):
    from hermes_mailcloud.rclone.runner import RcloneRunner

    return RcloneRunner(
        (
            sys.executable,
            "-I",
            "-X",
            "utf8",
            str(Path(__file__).resolve()),
            "backend",
            str(control_path),
        ),
        **kwargs,
    )


def cli_run(control: dict, control_path: Path, arguments: list[str]) -> None:
    import hermes_mailcloud.cli as cli
    from hermes_mailcloud.application import composition

    # S1 migration only: both seams create the actual installed runner.
    cli.RcloneRunner = lambda binary="rclone", **kwargs: executable_runner(control_path, **kwargs)
    composition.create_backend = lambda config, *, environment: executable_runner(
        control_path, environment=environment
    )
    sys.argv = ["hermes-mailcloud", *arguments]
    try:
        cli.app()
    finally:
        # Recheck after lazy component imports too; never emit raw journal data.
        Path(control["provenance"]).write_text(
            json.dumps(installed_provenance(control)), encoding="utf-8"
        )


def api_run(control: dict, control_path: Path) -> None:
    class NoCliSdk(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if (
                fullname.split(".")[0] in {"typer", "click", "rich", "PySide6", "mcp"}
                or fullname == "hermes_mailcloud.cli"
            ):
                raise RuntimeError("direct API imported a CLI SDK")

    require("hermes_mailcloud.cli" not in sys.modules, "CLI was pre-imported")
    sys.meta_path.insert(0, NoCliSdk())
    # This checks the runtime boundary before its first product import and never
    # imports CLI components. Full provenance runs in a separate probe process.
    installed_provenance(control, api_only=True)
    from hermes_mailcloud.application import CallOptions, MailCloudApplication, composition

    composition.create_backend = lambda config, *, environment: executable_runner(
        control_path, environment=environment
    )
    output, diagnostics = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(diagnostics):
        application = MailCloudApplication()
        results = {
            "version": application.version(),
            "ls": application.ls("/Hermes"),
            "stat": application.stat(control["api_stat_path"]),
            "refusal": application.ls("/Hermes", recursive=1),
            "failure": application.stat("/Hermes/private/api-failure"),
            "after_failure": application.ls("/Hermes"),
        }
        source, destination = Path(control["api_source"]), Path(control["api_destination"])
        source.write_bytes(b"installed API source")
        arguments = {
            "mkdir": ("/TEST/installed-api/directory",),
            "upload": (str(source), "/TEST/installed-api/file.txt"),
            "download": ("/TEST/installed-api/file.txt", str(destination)),
            "mv": ("/TEST/installed-api/file.txt", "/TEST/installed-api/moved.txt"),
            "cp": ("/TEST/installed-api/file.txt", "/TEST/installed-api/copied.txt"),
            "rm": ("/TEST/installed-api/file.txt",),
            "publish": (str(source), "/Hermes/public/installed-api.txt"),
            "link": ("/Hermes/public/installed-api.txt",),
        }
        for operation, args in arguments.items():
            results[operation] = getattr(application, operation)(
                *args, options=CallOptions(yes=True)
            )
        require(destination.read_bytes() == b"downloaded-wheel", "API download bytes changed")
        journal = Path(os.environ["HMC_LINKS_JOURNAL"])
        journal_before = journal.read_bytes()
        for operation, args in arguments.items():
            kwargs = {"overwrite": "always"} if operation == "download" else {}
            results["dry-" + operation] = getattr(application, operation)(
                *args, **kwargs, options=CallOptions(dry_run=True)
            )
        require(journal.read_bytes() == journal_before, "API dry-run mutated the journal")
        require(destination.read_bytes() == b"downloaded-wheel", "API dry-run changed destination")
        results["write-retries"] = application.mkdir(
            "/TEST/installed-api/retry", options=CallOptions(retries=1)
        )
        results["protected-rm"] = application.rm("/TEST", options=CallOptions(yes=True))
        results["write-bool"] = application.rm("/TEST/installed-api/file.txt", recursive="false")
        results["overwrite"] = application.upload(
            str(source), "/TEST/installed-api/file.txt", overwrite=True
        )
        results["confirmation"] = application.publish(*arguments["publish"])
        results["outside-public"] = application.link("/TEST/installed-api/file.txt")
        records = [json.loads(line) for line in journal_before.decode("utf-8").splitlines()]
        require(
            [row["operation"] for row in records] == ["publish", "link"],
            "API journal order changed",
        )
        require(
            all(row["public_url"] == PUBLIC_URL for row in records),
            "API journal capability mismatch",
        )
        resources = {
            "download_bytes": destination.stat().st_size,
            "download_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            "source_preserved": source.read_bytes() == b"installed API source",
            "journal_operations": [row["operation"] for row in records],
            "dry_run_journal_unchanged": journal.read_bytes() == journal_before,
        }
    require(not output.getvalue() and not diagnostics.getvalue(), "direct API wrote output")
    require(
        not any(name.split(".")[0] in {"typer", "click", "rich"} for name in sys.modules),
        "CLI SDK was loaded",
    )
    require("hermes_mailcloud.cli" not in sys.modules, "direct API loaded CLI")
    require(
        all(
            PUBLIC_URL not in repr(value) and DIAGNOSTIC not in repr(value)
            for value in results.values()
        ),
        "unsafe direct data",
    )
    provenance = installed_provenance(control, api_only=True)
    print(
        json.dumps(
            {
                "payloads": {name: value.to_payload() for name, value in results.items()},
                "exits": {name: value.exit_code for name, value in results.items()},
                "provenance": provenance,
                "cli_sdk_imported": False,
                "application_output": False,
                "resources": resources,
            }
        )
    )


def main() -> int:
    mode, filename, *arguments = sys.argv[1:]
    path = Path(filename).resolve()
    control = json.loads(path.read_text(encoding="utf-8"))
    if mode == "backend":
        return backend(control, arguments)
    if mode == "api":
        api_run(control, path)
        return 0
    provenance = installed_provenance(control)
    if mode == "probe":
        print(json.dumps(provenance))
    elif mode == "journal":
        from hermes_mailcloud.journal import _read_private_journal

        data = _read_private_journal(Path(control["journal"]))
        records = [json.loads(line) for line in data.splitlines()]
        require(bool(records) and data.endswith(b"\n"), "incomplete installed journal")
        require(
            all(row["version"] == 1 and row["public_url"] == PUBLIC_URL for row in records),
            "unexpected private journal record",
        )
        print(
            json.dumps(
                {
                    "count": len(records),
                    "operations": [row["operation"] for row in records],
                    "fingerprints": [row["public_url_fingerprint"] for row in records],
                    "private_read_passed": True,
                }
            )
        )
    elif mode == "cli":
        cli_run(control, path, arguments)
    else:
        raise RuntimeError("unknown installed test-driver mode")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

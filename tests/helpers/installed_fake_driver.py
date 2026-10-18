"""Standalone test-only argv driver; copy it outside the checkout before execution.

Only cli.RcloneRunner's executable argv is injected. All CLI, command, batch,
journal, platform and runner implementations must be the installed wheel's bytes.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import os
import sys
from pathlib import Path

PUBLIC_URL = "https://cloud.mail.ru/public/installed-wheel-synthetic-capability/path"
DIAGNOSTIC = "installed-backend-private-sentinel"
_COMPONENTS = (
    "hermes_mailcloud",
    "hermes_mailcloud.cli",
    "hermes_mailcloud.batch",
    "hermes_mailcloud.commands.public",
    "hermes_mailcloud.commands.transfer",
    "hermes_mailcloud.commands.read",
    "hermes_mailcloud.commands.mkdir",
    "hermes_mailcloud.commands.move_copy",
    "hermes_mailcloud.commands.remove",
    "hermes_mailcloud.journal",
    "hermes_mailcloud.rclone.runner",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def installed_provenance(control: dict) -> dict:
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
    modules = [importlib.import_module(name) for name in _COMPONENTS]
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
    cli = modules[1]
    for name, module in (
        ("BatchCommands", "hermes_mailcloud.batch"),
        ("PublicCommands", "hermes_mailcloud.commands.public"),
        ("TransferCommands", "hermes_mailcloud.commands.transfer"),
        ("ReadCommands", "hermes_mailcloud.commands.read"),
        ("MkdirCommand", "hermes_mailcloud.commands.mkdir"),
        ("MoveCopyCommands", "hermes_mailcloud.commands.move_copy"),
        ("RemoveCommand", "hermes_mailcloud.commands.remove"),
    ):
        require(
            getattr(cli, name) is getattr(importlib.import_module(module), name),
            "CLI component substitution",
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


def cli_run(control: dict, control_path: Path, arguments: list[str]) -> None:
    import hermes_mailcloud.cli as cli
    from hermes_mailcloud.rclone.runner import RcloneRunner

    class ExecutablePrefixRunner(RcloneRunner):
        def __init__(self, binary="rclone", **kwargs):
            super().__init__(
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

    cli.RcloneRunner = ExecutablePrefixRunner
    sys.argv = ["hermes-mailcloud", *arguments]
    try:
        cli.app()
    finally:
        # Recheck after lazy component imports too; never emit raw journal data.
        Path(control["provenance"]).write_text(
            json.dumps(installed_provenance(control)), encoding="utf-8"
        )


def main() -> int:
    mode, filename, *arguments = sys.argv[1:]
    path = Path(filename).resolve()
    control = json.loads(path.read_text(encoding="utf-8"))
    if mode == "backend":
        return backend(control, arguments)
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

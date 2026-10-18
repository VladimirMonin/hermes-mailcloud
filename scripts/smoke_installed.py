"""Clean-wheel smoke for Windows/Linux; no cloud, source import or launcher injection.

Run from the locked dev environment after ``uv build`` and a runtime-only locked
``uv export``. Every runtime process uses an external temporary cwd, an explicit
secret-free environment and the installed wheel. The copied test driver changes
only the executable argv seam, never the installed commands/journal/platform code.
"""

from __future__ import annotations

import argparse
import configparser
import ctypes
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from ctypes import wintypes
from email.parser import BytesParser
from pathlib import Path

PROJECT = "hermes-mailcloud"
PUBLIC_URL = "https://cloud.mail.ru/public/installed-wheel-synthetic-capability/path"
DIAGNOSTIC = "installed-backend-private-sentinel"
MAX_OUTPUT = 2 * 1024 * 1024


class SmokeFailure(RuntimeError):
    """A safe assertion failure; never attach raw backend/journal diagnostics."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def safe_diagnostic(text: str) -> str:
    """Retain useful local installer failures without capability/backend sentinels."""
    return re.sub(r"https?://\S+", "[redacted-url]", text.replace(DIAGNOSTIC, "[redacted]"))[-2000:]


def isolated_python(python: Path, *arguments: str) -> list[str]:
    # -I deliberately ignores PYTHONUTF8/PYTHONIOENCODING. Set the interpreter
    # mode explicitly too, so redirected Windows JSON is not tied to a codepage.
    return [str(python), "-I", "-X", "utf8", *arguments]


def runtime_paths(prefix: Path, *, windows: bool | None = None) -> tuple[Path, Path]:
    windows = os.name == "nt" if windows is None else windows
    directory = prefix / ("Scripts" if windows else "bin")
    return directory / ("python.exe" if windows else "python"), directory / (
        "hermes-mailcloud.exe" if windows else "hermes-mailcloud"
    )


def clean_environment(root: Path, cache: Path) -> dict[str, str]:
    paths = {
        "HOME": root / "home",
        "USERPROFILE": root / "home",
        "XDG_CONFIG_HOME": root / "config",
        "APPDATA": root / "appdata",
        "LOCALAPPDATA": root / "localappdata",
        "TEMP": root / "temp",
        "TMP": root / "temp",
        "TMPDIR": root / "temp",
    }
    for directory in paths.values():
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    (root / "empty-path").mkdir(exist_ok=True)
    (root / "empty-rclone.conf").write_text("", encoding="utf-8")
    (root / "config.toml").write_text("[profiles.default]\n", encoding="utf-8")
    environment = {name: str(path) for name, path in paths.items()}
    environment.update(
        {
            "PATH": str(root / "empty-path"),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TZ": "UTC",
            "NO_COLOR": "1",
            "TERM": "dumb",
            "UV_CACHE_DIR": str(cache),
            "UV_NO_PROGRESS": "1",
            "UV_PYTHON_DOWNLOADS": "never",
            "HMC_CONFIG": str(root / "config.toml"),
            "HMC_RCLONE_PATH": str(root / "no-real-rclone.exe"),
            "HMC_LINKS_JOURNAL": str(root / "private-journal" / "links.jsonl"),
            "RCLONE_CONFIG": str(root / "empty-rclone.conf"),
        }
    )
    if os.name == "nt":
        require(bool(os.environ.get("SystemRoot")), "SystemRoot is required on Windows")
        environment["SystemRoot"] = os.environ["SystemRoot"]
        environment["PATH"] += os.pathsep + str(Path(environment["SystemRoot"]) / "System32")
    return environment


def _identity(pid: int) -> tuple[int, str, str] | None:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return pid, fields[19], fields[0]
    except FileNotFoundError:
        return None


def _descendants() -> list[tuple[int, str, str]]:
    pending = [os.getpid()]
    found = set()
    while pending:
        pid = pending.pop()
        try:
            for task in Path(f"/proc/{pid}/task").iterdir():
                try:
                    for value in (task / "children").read_text().split():
                        child = int(value)
                        if child not in found:
                            found.add(child)
                            pending.append(child)
                except FileNotFoundError:
                    pass
        except FileNotFoundError:
            pass
    return [row for pid in sorted(found) if (row := _identity(pid)) is not None]


def _kill_exact(row: tuple[int, str, str]) -> None:
    # Ubuntu's libc exports pidfd APIs even when a portable CPython build omits
    # the optional os/signal wrappers. Keep native handles, never raw-PID signals.
    native = ctypes.CDLL(None, use_errno=True)
    try:
        open_handle = native.pidfd_open
        send_signal = native.pidfd_send_signal
    except AttributeError as exc:
        raise SmokeFailure("Linux smoke containment requires native pidfd APIs") from exc
    open_handle.argtypes = [ctypes.c_int, ctypes.c_uint]
    open_handle.restype = ctypes.c_int
    send_signal.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint]
    send_signal.restype = ctypes.c_int
    try:
        handle = open_handle(row[0], 0)
        if handle < 0:
            raise OSError(ctypes.get_errno(), "native pidfd_open failed")
    except ProcessLookupError:
        return
    try:
        current = _identity(row[0])
        if current and current[1] == row[1] and send_signal(handle, signal.SIGKILL, None, 0) != 0:
            raise OSError(ctypes.get_errno(), "native pidfd_send_signal failed")
    finally:
        os.close(handle)


class Commands:
    """Serial, bounded command containment; no product module is imported here.

    Windows uses a non-inherited KILL_ON_JOB_CLOSE Job around a suspended public
    pywin32 CreateProcess of our stdlib worker. It inherits no handles; the worker
    redirects the actual command to files, avoiding STARTUPINFOEX duplication.
    Linux uses an own-process subreaper and exact pidfd identities, including
    orphaned fake backends which the installed POSIX runner puts in new sessions.
    """

    def __init__(self, root: Path, environment: dict[str, str], deadline: float) -> None:
        self.root = root
        self.environment = environment
        self.deadline = deadline
        self.records: list[dict] = []
        self.last_release = True
        self.previous_subreaper = None
        self.worker = root / "command-worker.py"
        shutil.copyfile(__file__, self.worker)
        (root / "commands").mkdir()
        if os.name == "posix":
            require(sys.platform == "linux", "this smoke targets Windows and Linux")
            previous = ctypes.c_int()
            library = ctypes.CDLL(None, use_errno=True)
            require(
                library.prctl(37, ctypes.byref(previous), 0, 0, 0) == 0,
                "cannot inspect own child cleanup boundary",
            )
            require(
                library.prctl(36, 1, 0, 0, 0) == 0, "cannot establish own child cleanup boundary"
            )
            self.previous_subreaper = previous.value

    def close(self) -> None:
        if self.previous_subreaper is not None:
            require(
                ctypes.CDLL(None, use_errno=True).prctl(36, self.previous_subreaper, 0, 0, 0) == 0,
                "cannot restore own child cleanup boundary",
            )
            self.previous_subreaper = None

    def run(
        self,
        label: str,
        argv: list[str],
        *,
        environment: dict[str, str] | None = None,
        expected: int = 0,
    ) -> tuple[str, str]:
        self.last_release = False
        remaining = self.deadline - time.monotonic()
        require(remaining > 0, "installed smoke deadline exhausted")
        stem = self.root / "commands" / f"{len(self.records):03d}"
        spec = {
            "argv": argv,
            "cwd": str(self.root),
            "environment": environment or self.environment,
            "stdout": str(stem.with_suffix(".stdout")),
            "stderr": str(stem.with_suffix(".stderr")),
            "result": str(stem.with_suffix(".result")),
        }
        spec_path = stem.with_suffix(".json")
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        command = isolated_python(Path(sys.executable), str(self.worker), "_worker", str(spec_path))
        started = time.monotonic()
        timeout = min(60.0, remaining)
        release = (
            self._windows(command, timeout) if os.name == "nt" else self._linux(command, timeout)
        )
        require(release, "own command-tree cleanup was not confirmed")
        require(Path(spec["result"]).exists(), "command worker did not complete")
        result = json.loads(Path(spec["result"]).read_text(encoding="utf-8"))
        require("exit" in result, "command worker failed")
        streams = []
        for key in ("stdout", "stderr"):
            data = Path(spec[key]).read_bytes()
            require(len(data) <= MAX_OUTPUT, "command capture exceeded the smoke bound")
            streams.append(data.decode("utf-8", errors="replace"))
        self.records.append(
            {
                "label": label,
                "argv": argv,
                "exit": result["exit"],
                "seconds": time.monotonic() - started,
                "tree_released": release,
                "stdout_bytes": len(streams[0].encode()),
                "stderr_bytes": len(streams[1].encode()),
            }
        )
        if result["exit"] != expected:
            self.records[-1]["failure_stderr"] = safe_diagnostic(streams[1])
            self.records[-1]["failure_stdout"] = safe_diagnostic(streams[0])
        require(result["exit"] == expected, f"unexpected exit in {label}")
        return streams[0], streams[1]

    def _linux(self, command: list[str], timeout: float) -> bool:
        baseline = {(row[0], row[1]) for row in _descendants()}
        process = subprocess.Popen(
            command,
            cwd=self.root,
            env=self.environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        ok = True
        try:
            process.wait(timeout=timeout)
        except BaseException:
            ok = False
            raise
        finally:
            rows = [row for row in _descendants() if (row[0], row[1]) not in baseline]
            live = [row for row in rows if row[2] != "Z"]
            if live:
                ok = False
                for row in reversed(live):
                    _kill_exact(row)
            process.wait(timeout=2)
            for row in rows:
                try:
                    os.waitpid(row[0], 0)
                except ChildProcessError:
                    pass
            self.last_release = not any(
                row[2] != "Z" for row in _descendants() if (row[0], row[1]) not in baseline
            )
        return ok and self.last_release

    def _windows(self, command: list[str], timeout: float) -> bool:
        import win32api
        import win32event
        import win32job
        import win32process

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        job = kernel.CreateJobObjectW(None, None)  # NULL name: unnamed, non-inheritable.
        require(bool(job), "cannot create own command Job")
        process = thread = None
        assigned = False
        complete = False
        try:
            limits = win32job.QueryInformationJobObject(
                job, win32job.JobObjectExtendedLimitInformation
            )
            limits["BasicLimitInformation"]["LimitFlags"] = (
                win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            )
            win32job.SetInformationJobObject(
                job, win32job.JobObjectExtendedLimitInformation, limits
            )
            process, thread, _pid, _tid = win32process.CreateProcess(
                sys.executable,
                subprocess.list2cmdline(command),
                None,
                None,
                False,
                0x4 | 0x400 | 0x08000000,
                self.environment,
                str(self.root),
                win32process.STARTUPINFO(),
            )
            win32job.AssignProcessToJobObject(job, process)
            assigned = True
            win32process.ResumeThread(thread)
            thread.Close()
            thread = None
            require(
                win32event.WaitForSingleObject(process, int(timeout * 1000)) == 0,
                "command exceeded its deadline",
            )
            end = min(self.deadline, time.monotonic() + 2)
            while win32job.QueryInformationJobObject(
                job, win32job.JobObjectBasicAccountingInformation
            )["ActiveProcesses"]:
                require(time.monotonic() < end, "command left a live descendant")
                time.sleep(0.005)
            complete = True
        finally:
            try:
                if not complete and process is not None:
                    if assigned:
                        win32job.TerminateJobObject(job, 1)
                    else:
                        win32api.TerminateProcess(process, 1)
                end = time.monotonic() + 2
                while (
                    win32job.QueryInformationJobObject(
                        job, win32job.JobObjectBasicAccountingInformation
                    )["ActiveProcesses"]
                    and time.monotonic() < end
                ):
                    time.sleep(0.005)
                self.last_release = (
                    win32job.QueryInformationJobObject(
                        job, win32job.JobObjectBasicAccountingInformation
                    )["ActiveProcesses"]
                    == 0
                )
            finally:
                closed = bool(kernel.CloseHandle(job))
                self.last_release = self.last_release and closed
                if process is not None:
                    win32event.WaitForSingleObject(process, 2000)
                    process.Close()
                if thread is not None:
                    thread.Close()
        return complete and self.last_release


def _worker(spec_path: Path) -> int:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    result = {}
    try:
        with Path(spec["stdout"]).open("xb") as stdout, Path(spec["stderr"]).open("xb") as stderr:
            result["exit"] = subprocess.call(
                spec["argv"],
                cwd=spec["cwd"],
                env=spec["environment"],
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
            )
    except Exception as exc:
        result["worker_error"] = type(exc).__name__
    Path(spec["result"]).write_text(json.dumps(result), encoding="utf-8")
    return 0


def archive_has_no_runtime_state(names: list[str]) -> None:
    forbidden = {".hermes", ".venv", ".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".env"}
    require(
        not any(
            forbidden.intersection(name.replace("\\", "/").split("/"))
            or name.endswith((".pyc", ".pyo"))
            for name in names
        ),
        "runtime/private state leaked into a distribution",
    )


def distribution_info(directory: Path) -> dict:
    wheels, sdists = sorted(directory.glob("*.whl")), sorted(directory.glob("*.tar.gz"))
    require(len(wheels) == len(sdists) == 1, "exactly one wheel and sdist are required")
    with zipfile.ZipFile(wheels[0]) as archive:
        names = archive.namelist()
        archive_has_no_runtime_state(names)
        metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
        require(len(metadata_names) == 1, "wheel metadata is missing or ambiguous")
        metadata = BytesParser().parsebytes(archive.read(metadata_names[0]))
        require(metadata["Name"] == PROJECT, "unexpected wheel project")
        entry_points = configparser.ConfigParser()
        entry_points.read_string(
            archive.read(metadata_names[0].replace("METADATA", "entry_points.txt")).decode("utf-8")
        )
        entry_point = entry_points.get("console_scripts", PROJECT, fallback="")
        require(entry_point == "hermes_mailcloud.cli:app", "wrong installed console entry point")
        require(any(name.endswith("/LICENSE") for name in names), "wheel license is missing")
        require(
            not any(name.startswith(("tests/", "scripts/")) for name in names),
            "test sources leaked into wheel",
        )
        sources = {
            name: hashlib.sha256(archive.read(name)).hexdigest()
            for name in names
            if name.startswith("hermes_mailcloud/") and name.endswith(".py")
        }
    require("hermes_mailcloud/__init__.py" in sources, "wheel package source is missing")
    with tarfile.open(sdists[0]) as archive:
        names = archive.getnames()
        archive_has_no_runtime_state(names)
        pkg_info = [name for name in names if name.count("/") == 1 and name.endswith("/PKG-INFO")]
        require(len(pkg_info) == 1, "sdist metadata is missing")
        sdist_metadata = BytesParser().parsebytes(archive.extractfile(pkg_info[0]).read())
        require(
            sdist_metadata["Name"] == PROJECT and sdist_metadata["Version"] == metadata["Version"],
            "sdist and wheel metadata disagree",
        )
        require(any(name.endswith("/LICENSE") for name in names), "sdist license is missing")
    return {
        "wheel": str(wheels[0].resolve()),
        "sdist": str(sdists[0].resolve()),
        "version": metadata["Version"],
        "entry_point": entry_point,
        "sources": sources,
        "wheel_sha256": hashlib.sha256(wheels[0].read_bytes()).hexdigest(),
        "sdist_sha256": hashlib.sha256(sdists[0].read_bytes()).hexdigest(),
    }


def constraint_pins(path: Path) -> dict[str, str]:
    pins = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s;]+)(?:\s*;.*)?", line)
        require(match is not None, "runtime constraints must be pinned registry requirements")
        name, version = match.groups()
        pins[name.lower().replace("_", "-")] = version
    require(
        bool(pins) and PROJECT not in pins,
        "runtime constraints are empty or include source project",
    )
    return pins


def validators(directory: Path):
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    schemas = {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in directory.glob("*.schema.json")
    }
    registry = Registry().with_resources(
        (item["$id"], Resource.from_contents(item)) for item in schemas.values()
    )
    return {
        name: Draft202012Validator(schema, registry=registry) for name, schema in schemas.items()
    }


def json_envelope(stdout: str, stderr: str, *, operation: str, exit_code: int, validator) -> dict:
    require(not stderr, "JSON command wrote stderr")
    require(
        not any(value in stdout for value in ("\x1b", "Traceback", PUBLIC_URL, DIAGNOSTIC)),
        "unsafe JSON diagnostics",
    )
    payload = json.loads(stdout)
    validator.validate(payload)
    require(payload["operation"] == operation, "wrong JSON operation")
    if exit_code not in (0, 11):
        require(
            payload["ok"] is False and payload["error"]["exit_code"] == exit_code,
            "wrong typed error/exit",
        )
    else:
        require(payload["ok"] is (exit_code == 0), "wrong success/partial envelope")
    if operation == "batch" and "result" in payload:
        result = payload["result"]
        items = result["items"]
        require(
            result["total"] == len(items) == result["succeeded"] + result["failed"],
            "batch count invariant failed",
        )
        require([item["index"] for item in items] == list(range(len(items))), "batch order failed")
        require(
            result["succeeded"] == sum(item["ok"] for item in items), "batch outcome count failed"
        )
    return payload


def exercise(
    runtime: Path,
    launcher: Path,
    root: Path,
    checkout: Path,
    info: dict,
    pins: dict,
    commands: Commands,
    schema_dir: Path,
    driver_source: Path,
) -> dict:
    driver = root / "installed-fake-driver.py"
    shutil.copyfile(driver_source, driver)
    validate = validators(schema_dir)
    environment = commands.environment
    control = {
        "prefix": str(runtime.parent.parent),
        "checkout": str(checkout),
        "version": info["version"],
        "sources": info["sources"],
        "log": str(root / "backend-calls.jsonl"),
        "journal": environment["HMC_LINKS_JOURNAL"],
        "provenance": str(root / "provenance.json"),
    }
    control_path = root / "control.json"
    control_path.write_text(json.dumps(control), encoding="utf-8")
    prefix = isolated_python(runtime, str(driver))
    stdout, stderr = commands.run(
        "installed-import-provenance", [*prefix, "probe", str(control_path)]
    )
    require(not stderr, "installed provenance wrote diagnostics")
    provenance = json.loads(stdout)
    require(provenance["isolated"] and provenance["utf8_mode"], "runtime isolation/UTF-8 mode lost")
    require(
        all(
            name == PROJECT or pins.get(name) == version
            for name, version in provenance["installed"].items()
        ),
        "runtime dependency not locked",
    )
    require(provenance["version"] == info["version"], "runtime version mismatch")
    stdout, _ = commands.run("console-help-no-injection", [str(launcher), "--help"])
    require("Usage" in stdout and "doctor" in stdout, "installed launcher help failed")
    stdout, stderr = commands.run("console-version-no-injection", [str(launcher), "version"])
    require(not stderr and stdout.strip() == info["version"], "installed launcher version failed")
    for operation in ("version", "doctor"):
        stdout, stderr = commands.run(
            "console-json-" + operation + "-no-injection", [str(launcher), "--json", operation]
        )
        payload = json_envelope(
            stdout,
            stderr,
            operation=operation,
            exit_code=0,
            validator=validate[
                "doctor-report.schema.json"
                if operation == "doctor"
                else "result-envelope.schema.json"
            ],
        )
        if operation == "doctor":
            require(payload["result"]["mode"] == "read_only", "doctor was not read-only")
            checks = payload["result"]["checks"]
            require(
                checks["rclone_installed"] is False
                and checks["cloud_access"] is False
                and checks["remote_configured"] is False,
                "doctor reached configured runtime",
            )
            require(
                set(payload["result"]["capabilities"].values()) == {"unknown"},
                "doctor claimed unproven capabilities",
            )
        else:
            require(payload["result"]["version"] == info["version"], "JSON version mismatch")
    scenarios = []
    fake_environment = {**environment, "HMC_REMOTE": "fake:"}

    def calls() -> list:
        path = Path(control["log"])
        return (
            [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            if path.exists()
            else []
        )

    def case(
        label: str,
        arguments: list[str],
        operation: str,
        *,
        expected: int = 0,
        expected_kind: str | None = None,
        no_backend: bool = False,
        failure_target: str | None = None,
        journal: Path | None = None,
    ) -> tuple[dict, list]:
        previous = calls()
        control["failure_target"] = failure_target
        control["provenance"] = str(root / (label + "-provenance.json"))
        control_path.write_text(json.dumps(control), encoding="utf-8")
        selected = dict(fake_environment)
        if journal is not None:
            selected["HMC_LINKS_JOURNAL"] = str(journal)
        stdout, stderr = commands.run(
            label,
            [*prefix, "cli", str(control_path), *arguments],
            environment=selected,
            expected=expected,
        )
        payload = json_envelope(
            stdout,
            stderr,
            operation=operation,
            exit_code=expected,
            validator=validate["result-envelope.schema.json"],
        )
        if expected_kind is not None:
            require(payload["error"]["kind"] == expected_kind, "wrong safety/error discriminator")
        if journal is not None and expected:
            require(str(journal) not in stdout, "private journal path leaked in diagnostics")
        stamp = json.loads(Path(control["provenance"]).read_text(encoding="utf-8"))
        require(
            stamp["loaded_components"] == provenance["loaded_components"],
            "installed components changed during CLI execution",
        )
        new_calls = calls()[len(previous) :]
        require(not no_backend or not new_calls, "preflight/dry-run started a backend")
        scenarios.append(
            {
                "name": label,
                "exit": expected,
                "operation": operation,
                "backend_calls": len(new_calls),
                "ok": payload["ok"],
            }
        )
        return payload, new_calls

    source = root / "local ü & files" / "report 'literal'.txt"
    source.parent.mkdir()
    source.write_text("synthetic wheel payload", encoding="utf-8")
    destination = source.with_name("downloaded 'literal'.txt")
    remote = "/Hermes/private/report ü &;$%.txt"
    for label, arguments, operation in (
        ("file-ls", ["ls", "/Hermes", "--json"], "ls"),
        ("file-stat", ["stat", remote, "--json"], "stat"),
        ("file-mkdir", ["mkdir", "/Hermes/private/wheel", "--json"], "mkdir"),
        ("file-upload", ["upload", str(source), remote, "--json"], "upload"),
        ("file-download", ["download", remote, str(destination), "--json"], "download"),
        ("file-move", ["mv", remote, "/Hermes/private/moved.txt", "--json"], "mv"),
        ("file-copy", ["cp", remote, "/Hermes/private/copied.txt", "--json"], "cp"),
        ("file-remove", ["rm", remote, "--json", "--yes"], "rm"),
    ):
        _, invoked = case(label, arguments, operation)
        require(len(invoked) == 1, "file command was not executed exactly once")
        if operation == "upload":
            require(
                invoked[0] == ["copyto", str(source), "fake:" + remote, "--immutable"],
                "literal upload argv changed",
            )
    require(
        destination.read_bytes() == b"downloaded-wheel", "installed download did not commit bytes"
    )
    public = "/Hermes/public/report ü &;$%.txt"
    for operation in ("publish", "link"):
        argv = [operation, str(source), public] if operation == "publish" else [operation, public]
        if operation == "publish":
            argv.append("--yes")
        payload, invoked = case("public-" + operation, [*argv, "--json"], operation)
        require(
            [row[0] for row in invoked]
            == (["copyto", "link"] if operation == "publish" else ["link"]),
            "public operation did not reach the installed backend seam",
        )
        require(
            payload["result"]["public_url_fingerprint"].startswith("sha256:"),
            "public result has no fingerprint",
        )

    def plan(name: str, operations: list[dict], *, continue_on_error: bool = False) -> Path:
        path = root / (name + ".json")
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "defaults": {"continue_on_error": continue_on_error},
                    "operations": operations,
                }
            ),
            encoding="utf-8",
        )
        return path

    public_plan = plan(
        "public-plan",
        [
            {"op": "mkdir", "remote_path": "/Hermes/private/batch"},
            {"op": "publish", "local_path": str(source), "remote_path": public},
            {"op": "link", "remote_path": public},
        ],
    )
    payload, invoked = case(
        "batch-public-success", ["batch", str(public_plan), "--yes", "--json"], "batch"
    )
    require(
        payload["result"]["succeeded"] == 3
        and [row[0] for row in invoked] == ["mkdir", "copyto", "link", "link"],
        "installed public batch vertical failed",
    )
    control_path.write_text(json.dumps(control), encoding="utf-8")
    stdout, stderr = commands.run(
        "installed-private-journal-read", [*prefix, "journal", str(control_path)]
    )
    require(not stderr and PUBLIC_URL not in stdout, "journal inspection leaked a capability")
    journal_result = json.loads(stdout)
    require(
        journal_result["private_read_passed"]
        and journal_result["operations"] == ["publish", "link", "publish", "link"],
        "installed private journal records differ",
    )
    before_journal = hashlib.sha256(Path(control["journal"]).read_bytes()).hexdigest()
    dangerous = source.with_name(".env")
    dangerous.write_text("synthetic only", encoding="utf-8")
    for label, arguments, operation, code, kind in (
        (
            "unsafe-public",
            ["link", "/Hermes/private/secret.txt", "--json"],
            "link",
            9,
            "unsafe_public_path",
        ),
        (
            "dangerous-public",
            ["publish", str(dangerous), "/Hermes/public/.env", "--yes", "--json"],
            "publish",
            9,
            "dangerous_file_pattern",
        ),
        ("confirmation", ["rm", remote, "--json"], "rm", 9, "confirmation_required"),
        (
            "publish-confirmation",
            ["publish", str(source), public, "--json"],
            "publish",
            9,
            "confirmation_required",
        ),
        ("protected-root", ["rm", "/", "--yes", "--json"], "rm", 2, "invalid_arguments"),
        (
            "write-retries",
            ["--retries", "1", "mkdir", "/Hermes/private/no", "--json"],
            "mkdir",
            2,
            "invalid_arguments",
        ),
    ):
        case(label, arguments, operation, expected=code, expected_kind=kind, no_backend=True)
    bad_journal = root / "not-a-journal-file"
    bad_journal.mkdir()
    case(
        "public-journal-preflight",
        ["link", public, "--json"],
        "link",
        expected=1,
        expected_kind="unknown_error",
        no_backend=True,
        journal=bad_journal,
    )
    case(
        "batch-journal-preflight",
        ["batch", str(public_plan), "--yes", "--json"],
        "batch",
        expected=1,
        expected_kind="unknown_error",
        no_backend=True,
        journal=bad_journal,
    )
    dry_journal = root / "dry-private-state" / "links.jsonl"
    require(not dry_journal.parent.exists(), "dry-run fixture was already initialized")
    for label, arguments, operation in (
        ("file-dry-run", ["mkdir", "/Hermes/private/dry", "--dry-run", "--json"], "mkdir"),
        ("public-dry-run", ["publish", str(source), public, "--dry-run", "--json"], "publish"),
        ("batch-dry-run", ["batch", str(public_plan), "--dry-run", "--json"], "batch"),
    ):
        payload, _ = case(label, arguments, operation, no_backend=True, journal=dry_journal)
        if operation == "batch":
            require(
                all(item["result"].get("dry_run") is True for item in payload["result"]["items"]),
                "batch dry-run did not return planned operations",
            )
        else:
            require(payload["result"].get("dry_run") is True, "dry-run result flag is missing")
            if operation == "publish":
                require(payload["result"]["published"] is False, "dry-run claimed publication")
    require(not dry_journal.parent.exists(), "dry-run created journal state")
    failure = "fake:/Hermes/private/backend-fail"
    payload, invoked = case(
        "backend-failure",
        ["mkdir", failure.removeprefix("fake:"), "--json"],
        "mkdir",
        expected=10,
        failure_target=failure,
    )
    require(
        payload["error"]["kind"] == "network_error" and len(invoked) == 1,
        "backend failure contract/retry changed",
    )
    for continuation in (False, True):
        partial = plan(
            "partial-" + str(continuation),
            [
                {"op": "mkdir", "remote_path": failure.removeprefix("fake:")},
                {"op": "mkdir", "remote_path": "/Hermes/private/after-failure"},
            ],
            continue_on_error=continuation,
        )
        payload, invoked = case(
            "batch-partial-" + str(continuation),
            ["batch", str(partial), "--yes", "--json"],
            "batch",
            expected=11,
            failure_target=failure,
        )
        require(
            payload["result"]["status"] == "partial_failure"
            and payload["result"]["total"] == (2 if continuation else 1)
            and payload["result"]["failed"] == 1
            and payload["result"]["succeeded"] == (1 if continuation else 0)
            and payload["result"]["items"][0]["error"]["kind"] == "network_error"
            and len(invoked) == (2 if continuation else 1),
            "partial stop/continue failed",
        )
    require(
        hashlib.sha256(Path(control["journal"]).read_bytes()).hexdigest() == before_journal,
        "failure/dry-run changed the private journal",
    )
    return {
        "provenance": provenance,
        "scenarios": scenarios,
        "journal": journal_result,
        "real_console_launcher": True,
        "console_injection": False,
        "fake_backed_only": True,
        "real_rclone": "NOT RUN: no trusted executable provided",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--constraints", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--uv", default=shutil.which("uv"))
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--timeout", type=float, default=105)
    parser.add_argument("--temp-parent", type=Path)
    args = parser.parse_args()
    checkout = Path(__file__).resolve().parents[1]
    require(args.uv is not None, "uv executable is required")
    require(0 < args.timeout <= 108, "smoke timeout must be in (0,108]")
    require(not args.receipt.exists(), "receipt already exists")
    info = distribution_info(args.dist_dir.resolve())
    pins = constraint_pins(args.constraints.resolve())
    receipt = {
        "status": "FAIL",
        "distribution": {key: value for key, value in info.items() if key != "sources"},
        "context": {"python": sys.version, "platform": sys.platform},
        "constraints_sha256": hashlib.sha256(args.constraints.read_bytes()).hexdigest(),
        "commands": [],
    }
    temporary = tempfile.TemporaryDirectory(prefix="hermes-installed-", dir=args.temp_parent)
    root = Path(temporary.name).resolve()
    commands = None
    try:
        require(not root.is_relative_to(checkout), "smoke sandbox must be outside checkout")
        environment = clean_environment(root, args.cache_dir.resolve())
        commands = Commands(root, environment, time.monotonic() + args.timeout)
        uv_options = [str(Path(args.uv).resolve()), "--no-config"]
        if args.offline:
            uv_options.append("--offline")
        prefix = root / "runtime"
        commands.run(
            "clean-runtime-create", [*uv_options, "venv", "--python", sys.executable, str(prefix)]
        )
        python, launcher = runtime_paths(prefix)
        commands.run(
            "wheel-runtime-install",
            [
                *uv_options,
                "pip",
                "install",
                "--python",
                str(python),
                "--no-build",
                "--strict",
                "--constraints",
                str(args.constraints.resolve()),
                info["wheel"],
            ],
        )
        receipt.update(
            exercise(
                python,
                launcher,
                root,
                checkout,
                info,
                pins,
                commands,
                checkout / "schemas",
                checkout / "tests/helpers/installed_fake_driver.py",
            )
        )
        receipt["status"] = "PASS"
    except Exception as exc:
        receipt["failure"] = {
            "type": type(exc).__name__,
            "message": str(exc)
            .replace(PUBLIC_URL, "[redacted]")
            .replace(DIAGNOSTIC, "[redacted]")[:1000],
        }
    finally:
        if commands is not None:
            receipt["commands"] = commands.records
            receipt["last_command_tree_released"] = commands.last_release
            try:
                commands.close()
            except SmokeFailure:
                receipt["status"] = "FAIL"
                receipt["cleanup_failure"] = "own process cleanup boundary was not restored"
        try:
            temporary.cleanup()
            receipt["sandbox_removed"] = True
        except OSError:
            receipt["sandbox_removed"] = False
            receipt["status"] = "FAIL"
            receipt["cleanup_failure"] = "own temporary sandbox could not be removed"
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "version": info["version"],
                "scenarios": len(receipt.get("scenarios", [])),
                "commands": len(receipt["commands"]),
                "sandbox_removed": receipt["sandbox_removed"],
            }
        )
    )
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "_worker":
        raise SystemExit(_worker(Path(sys.argv[2])))
    raise SystemExit(main())

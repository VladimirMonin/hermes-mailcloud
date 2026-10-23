"""Controls for the portable clean-wheel/CI harness (real seam runs are separate)."""

from __future__ import annotations

import errno
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import textwrap
import time
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_ci_covers_both_target_oses_and_python_versions_without_bash_smoke() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "windows-latest" in workflow
    assert "ubuntu-latest" in workflow
    assert '"3.12"' in workflow and '"3.13"' in workflow
    assert "uv sync --locked --all-groups --all-extras" in workflow
    assert "uv build" in workflow
    assert "scripts/smoke_installed.py" in workflow
    assert "mktemp" not in workflow and "env -i" not in workflow and "trap " not in workflow
    assert "secrets." not in workflow


def test_ci_job_environment_uses_only_pre_runner_contexts() -> None:
    # GitHub rejects runner/steps/env contexts here before it can create jobs.
    # https://docs.github.com/en/actions/reference/workflows-and-actions/contexts
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    job_environments = re.findall(r"(?m)^    env:\n((?:      .*\n)+)", workflow)
    assert job_environments
    available = {"github", "needs", "strategy", "matrix", "vars", "secrets", "inputs"}
    for environment in job_environments:
        for expression in re.findall(r"\$\{\{(.*?)\}\}", environment, re.DOTALL):
            references = set(re.findall(r"\b([A-Za-z_]\w*)\s*[.\[]", expression))
            assert references <= available, references - available


def test_ci_uv_cache_is_selected_after_runner_start(tmp_path: Path, monkeypatch) -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    runtime = workflow.split("\n  runtime:\n", 1)[1]
    name = "- name: Select runner-local uv cache\n"
    assert runtime.index(name) < runtime.index("uses: astral-sh/setup-uv@")
    assert runtime.index(name) < runtime.index("uv sync --locked")
    step = runtime.split(name, 1)[1].split("\n      - ", 1)[0]
    assert "shell: python" in step
    source = textwrap.dedent(step.split("run: |\n", 1)[1])
    runner_temp = tmp_path / "runner temp Ж"
    environment_file = tmp_path / "github-env.txt"
    monkeypatch.setenv("RUNNER_TEMP", str(runner_temp))
    monkeypatch.setenv("GITHUB_ENV", str(environment_file))

    exec(compile(source, "<CI cache bootstrap>", "exec"), {})

    assert environment_file.read_text(encoding="utf-8") == (
        f"UV_CACHE_DIR={runner_temp / 'mailcloud-uv-cache'}\n"
    )


def test_ci_test_packs_are_a_disjoint_cover_of_all_test_modules() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert workflow.count("python -m pytest") == 5
    assert "Offline application API pack" in workflow
    assert len(re.findall(r"\btests/application\b", workflow)) == 1
    selected = {ROOT / value for value in re.findall(r"\btests/[A-Za-z0-9_./-]+", workflow)}
    modules = sorted((ROOT / "tests").rglob("test_*.py"))
    assert modules
    for module in modules:
        matches = [path for path in selected if module == path or module.is_relative_to(path)]
        assert len(matches) == 1, (module.relative_to(ROOT), matches)


@pytest.fixture(scope="module")
def smoke():
    spec = importlib.util.spec_from_file_location(
        "_installed_smoke_controls", ROOT / "scripts/smoke_installed.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("windows", [False, True])
def test_runtime_paths_use_the_target_platform_layout(smoke, windows: bool) -> None:
    prefix = Path("isolated-runtime")
    python, launcher = smoke.runtime_paths(prefix, windows=windows)
    assert python == prefix / ("Scripts/python.exe" if windows else "bin/python")
    assert launcher == prefix / (
        "Scripts/hermes-mailcloud.exe" if windows else "bin/hermes-mailcloud"
    )


def test_isolated_runtime_explicitly_round_trips_unicode_without_locale_environment(
    smoke,
    tmp_path: Path,
) -> None:
    environment = smoke.clean_environment(tmp_path, tmp_path / "own-cache")
    environment.update(PYTHONUTF8="0", PYTHONIOENCODING="cp1251")
    result = subprocess.run(
        smoke.isolated_python(
            Path(sys.executable), "-c", "import sys; assert sys.flags.isolated; print('отчёт ü &')"
        ),
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 0 and result.stderr == b""
    assert result.stdout.decode("utf-8").strip() == "отчёт ü &"


def test_runtime_environment_does_not_inherit_source_or_secret_settings(
    smoke,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in (
        "PYTHONPATH",
        "PYTHONHOME",
        "HMC_REMOTE",
        "RCLONE_PASSWORD",
        "HTTP_PROXY",
        "UV_OFFLINE",
        "UV_NO_SYNC",
    ):
        monkeypatch.setenv(key, "forbidden-inherited-sentinel")
    environment = smoke.clean_environment(tmp_path, tmp_path / "own-cache")
    assert "forbidden-inherited-sentinel" not in json.dumps(environment)
    assert "PYTHONPATH" not in environment and "PYTHONHOME" not in environment
    assert "HMC_REMOTE" not in environment and "RCLONE_PASSWORD" not in environment
    assert environment["HOME"] == str(tmp_path / "home")
    assert Path(environment["HMC_CONFIG"]).read_text() == "[profiles.default]\n"
    assert not Path(environment["HMC_RCLONE_PATH"]).exists()


@pytest.mark.parametrize("contents", ["", "typer>=0.12\n", "-e .\n", "hermes-mailcloud==0.1.0a0\n"])
def test_runtime_constraints_must_be_pinned_and_not_the_editable_project(
    smoke,
    tmp_path: Path,
    contents: str,
) -> None:
    constraints = tmp_path / "constraints.txt"
    constraints.write_text(contents, encoding="utf-8")
    with pytest.raises(smoke.SmokeFailure):
        smoke.constraint_pins(constraints)


def test_runtime_constraints_keep_conditional_platform_pins(smoke, tmp_path: Path) -> None:
    constraints = tmp_path / "constraints.txt"
    constraints.write_text(
        'typer==0.24.1\npywin32==312 ; sys_platform == "win32"\n', encoding="utf-8"
    )
    assert smoke.constraint_pins(constraints) == {"typer": "0.24.1", "pywin32": "312"}


@pytest.mark.parametrize(
    "poison",
    [
        "\x1b[31m",
        "Traceback",
        "https://cloud.mail.ru/public/installed-wheel-synthetic-capability/path",
        "installed-backend-private-sentinel",
    ],
)
def test_json_validation_rejects_unsafe_output_before_schema_diagnostics(
    smoke, poison: str
) -> None:
    class MustNotValidate:
        def validate(self, _payload):
            pytest.fail("unsafe output reached schema diagnostics")

    with pytest.raises(smoke.SmokeFailure, match="unsafe JSON"):
        smoke.json_envelope(
            json.dumps({"value": poison}, ensure_ascii=False).replace("\\u001b", "\x1b"),
            "",
            operation="version",
            exit_code=0,
            validator=MustNotValidate(),
        )


def test_installer_failure_diagnostics_redact_urls_and_backend_sentinels(smoke) -> None:
    text = (
        "download failed https://example.invalid/private-token installed-backend-private-sentinel"
    )
    safe = smoke.safe_diagnostic(text)
    assert "https://" not in safe and "private-token" not in safe
    assert "installed-backend-private-sentinel" not in safe
    assert "download failed" in safe


def test_json_validation_uses_real_schema_and_frozen_batch_invariants(smoke) -> None:
    validator = smoke.validators(ROOT / "schemas")["result-envelope.schema.json"]
    payload = {
        "ok": False,
        "operation": "batch",
        "result": {
            "status": "partial_failure",
            "exit_code": 11,
            "total": 2,
            "succeeded": 0,
            "failed": 2,
            "items": [
                {
                    "index": 0,
                    "operation": "mkdir",
                    "ok": False,
                    "error": {"kind": "network_error", "exit_code": 10, "message": "safe"},
                }
            ],
        },
    }
    with pytest.raises(smoke.SmokeFailure, match="count invariant"):
        smoke.json_envelope(
            json.dumps(payload), "", operation="batch", exit_code=11, validator=validator
        )
    valid = {"ok": True, "operation": "version", "result": {"version": "0.1.0a0"}}
    assert (
        smoke.json_envelope(
            json.dumps(valid), "", operation="version", exit_code=0, validator=validator
        )
        == valid
    )


def _archives(
    root: Path,
    *,
    wheel_license=True,
    sdist_license=True,
    sdist_version="0.1.0a0",
    runtime_leak=False,
    omitted_application=None,
) -> None:
    metadata = b"Name: hermes-mailcloud\nVersion: 0.1.0a0\nLicense-Expression: MIT\n\n"
    with zipfile.ZipFile(root / "hermes_mailcloud-0.1.0a0-py3-none-any.whl", "w") as archive:
        archive.writestr("hermes_mailcloud-0.1.0a0.dist-info/METADATA", metadata)
        archive.writestr(
            "hermes_mailcloud-0.1.0a0.dist-info/entry_points.txt",
            "[console_scripts]\nhermes-mailcloud = hermes_mailcloud.cli:app\n",
        )
        archive.writestr("hermes_mailcloud/__init__.py", '__version__ = "0.1.0a0"\n')
        for name in ("__init__", "contracts", "validation", "composition", "service"):
            if name != omitted_application:
                archive.writestr(f"hermes_mailcloud/application/{name}.py", b"# synthetic source\n")
        if wheel_license:
            archive.writestr("hermes_mailcloud-0.1.0a0.dist-info/licenses/LICENSE", "MIT License")
    with tarfile.open(root / "hermes_mailcloud-0.1.0a0.tar.gz", "w:gz") as archive:
        files = {"PKG-INFO": metadata.replace(b"0.1.0a0", sdist_version.encode())}
        if sdist_license:
            files["LICENSE"] = b"MIT License"
        if runtime_leak:
            files[".hermes/runtime-state.json"] = b"synthetic runtime state"
        for name, data in files.items():
            info = tarfile.TarInfo("hermes_mailcloud-0.1.0a0/" + name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


@pytest.mark.parametrize(
    "missing", ["wheel-license", "sdist-license", "version-mismatch", "runtime-state"]
)
def test_distribution_gate_rejects_missing_licenses_and_inconsistent_metadata(
    smoke,
    tmp_path: Path,
    missing: str,
) -> None:
    _archives(
        tmp_path,
        wheel_license=missing != "wheel-license",
        sdist_license=missing != "sdist-license",
        sdist_version="9.9.9" if missing == "version-mismatch" else "0.1.0a0",
        runtime_leak=missing == "runtime-state",
    )
    with pytest.raises(smoke.SmokeFailure):
        smoke.distribution_info(tmp_path)


def test_distribution_gate_pins_real_archive_source_bytes(smoke, tmp_path: Path) -> None:
    _archives(tmp_path)
    info = smoke.distribution_info(tmp_path)
    assert info["version"] == "0.1.0a0"
    assert info["entry_point"] == "hermes_mailcloud.cli:app"
    assert len(info["sources"]["hermes_mailcloud/__init__.py"]) == 64
    for name in ("__init__", "contracts", "validation", "composition", "service"):
        assert (
            info["sources"][f"hermes_mailcloud/application/{name}.py"]
            == hashlib.sha256(b"# synthetic source\n").hexdigest()
        )
    assert len(info["wheel_sha256"]) == len(info["sdist_sha256"]) == 64


@pytest.mark.parametrize("name", ["__init__", "contracts", "validation", "composition", "service"])
def test_wheel_gate_requires_every_application_module(smoke, tmp_path: Path, name: str) -> None:
    _archives(tmp_path, omitted_application=name)
    with pytest.raises(smoke.SmokeFailure, match="application source is missing"):
        smoke.distribution_info(tmp_path)


@pytest.mark.parametrize("mode", ["probe", "api"])
def test_standalone_driver_rejects_a_source_checkout_runtime_before_component_import(
    smoke,
    tmp_path: Path,
    mode: str,
) -> None:
    driver = tmp_path / "copied-driver.py"
    shutil.copyfile(ROOT / "tests/helpers/installed_fake_driver.py", driver)
    control = tmp_path / "control.json"
    control.write_text(json.dumps({"prefix": sys.prefix, "checkout": str(ROOT)}), encoding="utf-8")
    result = subprocess.run(
        smoke.isolated_python(Path(sys.executable), str(driver), mode, str(control)),
        cwd=ROOT,
        env=smoke.clean_environment(tmp_path, tmp_path / "own-cache"),
        capture_output=True,
        timeout=5,
    )
    assert result.returncode != 0 and result.stdout == b""
    assert b"checkout" in result.stderr


def test_fake_probe_download_preserves_native_text_payload_bytes(tmp_path: Path) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_fixture_driver", ROOT / "tests/helpers/installed_fake_driver.py"
    )
    driver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
    source, destination = tmp_path / "source.txt", tmp_path / "downloaded.txt"
    source.write_text("hermes-mailcloud probe\n", encoding="utf-8")
    code = driver.backend(
        {"log": str(tmp_path / "calls.jsonl")},
        ["copyto", "fake:/TEST/hermes-mailcloud-fixture/probe.txt", str(destination)],
    )
    assert code == 0 and destination.read_bytes() == source.read_bytes()


def test_command_deadline_kills_an_actually_started_own_worker_tree(smoke, tmp_path: Path) -> None:
    ready = tmp_path / "self-ready.json"
    nonce = uuid.uuid4().hex
    code = (
        "import json,os,sys,time; from pathlib import Path; "
        "Path(sys.argv[1]).write_text(json.dumps({'pid':os.getpid(),'nonce':sys.argv[2]})); "
        "time.sleep(10)"
    )
    environment = smoke.clean_environment(tmp_path, tmp_path / "own-cache")
    commands = smoke.Commands(tmp_path, environment, time.monotonic() + 1.5)
    try:
        with pytest.raises((smoke.SmokeFailure, subprocess.TimeoutExpired)):
            commands.run("timeout-control", [sys.executable, "-I", "-c", code, str(ready), nonce])
        payload = json.loads(ready.read_text())
        assert payload["nonce"] == nonce and payload["pid"] > 0
        assert commands.last_release is True
        if os.name == "posix":
            assert smoke._descendants() == []
    finally:
        commands.close()


@pytest.mark.parametrize(
    "outcome", ["matching", "reused", "gone", "open-missing", "open-denied", "signal-denied"]
)
def test_pidfd_cleanup_uses_native_handles_without_optional_python_wrappers(
    smoke, monkeypatch, outcome: str
) -> None:
    row = (54321, "original-creation", "S")
    calls = []
    closed = []
    native_errno = errno.ESRCH if outcome == "open-missing" else errno.EPERM

    def open_pidfd(pid, flags):
        calls.append(("open", pid, flags))
        return -1 if outcome.startswith("open-") else 77

    def send_signal(handle, signum, info, flags):
        calls.append(("signal", handle, signum, info, flags))
        return -1 if outcome == "signal-denied" else 0

    native = SimpleNamespace(pidfd_open=open_pidfd, pidfd_send_signal=send_signal)

    def load_native(name, **options):
        assert name is None and options == {"use_errno": True}
        return native

    # Replace only this harness module's bindings, never shared os/signal/ctypes APIs.
    monkeypatch.setattr(
        smoke,
        "ctypes",
        SimpleNamespace(
            **(vars(smoke.ctypes) | {"CDLL": load_native, "get_errno": lambda: native_errno})
        ),
    )
    monkeypatch.setattr(smoke, "os", SimpleNamespace(close=closed.append))
    monkeypatch.setattr(smoke, "signal", SimpleNamespace(SIGKILL=9))
    identity = None if outcome == "gone" else row
    if outcome == "reused":
        identity = (row[0], "different-creation", "S")
    monkeypatch.setattr(smoke, "_identity", lambda pid: identity)

    if outcome in {"open-denied", "signal-denied"}:
        with pytest.raises(OSError) as failure:
            smoke._kill_exact(row)
        assert failure.value.errno == native_errno
    else:
        smoke._kill_exact(row)
    assert calls[0] == ("open", row[0], 0)
    assert open_pidfd.argtypes == [smoke.ctypes.c_int, smoke.ctypes.c_uint]
    assert open_pidfd.restype is smoke.ctypes.c_int
    assert send_signal.argtypes == [
        smoke.ctypes.c_int,
        smoke.ctypes.c_int,
        smoke.ctypes.c_void_p,
        smoke.ctypes.c_uint,
    ]
    assert send_signal.restype is smoke.ctypes.c_int
    assert closed == ([] if outcome.startswith("open-") else [77])
    assert calls[1:] == (
        [("signal", 77, 9, None, 0)] if outcome in {"matching", "signal-denied"} else []
    )

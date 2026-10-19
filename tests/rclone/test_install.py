"""Deterministic installer security/lifetime controls; no network or real rclone."""

from __future__ import annotations

import hashlib
import importlib
import io
import json
import os
import stat
import threading
import urllib.error
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.helpers.rclone_install import archive_fixture, environment

from hermes_mailcloud.core.errors import MailCloudError


@pytest.fixture
def install():
    return importlib.import_module("hermes_mailcloud.rclone.install")


@pytest.fixture
def fixture(install, monkeypatch, tmp_path):
    values = environment(tmp_path)
    system = "windows" if os.name == "nt" else "linux"
    payload, specification, executable = archive_fixture(system)
    release = install.Release(**specification)
    monkeypatch.setattr(install, "pinned_release", lambda: release)
    verified = []

    def verify(path, *, expected_version, environment, timeout_seconds):
        assert path.read_bytes() == executable
        verified.append(path)
        return expected_version

    monkeypatch.setattr(install, "_verify_executable", verify)
    archive = tmp_path / "official-fixture.zip"
    archive.write_bytes(payload)
    return SimpleNamespace(
        env=values,
        payload=payload,
        release=release,
        executable=executable,
        archive=archive,
        verified=verified,
        root=install.managed_data_root(values),
    )


class Response(io.BytesIO):
    def __init__(self, payload, url, *, headers=None, status=200):
        super().__init__(payload)
        self.url = url
        self.status = status
        self.headers = {"Content-Length": str(len(payload))} if headers is None else headers

    def geturl(self):
        return self.url

    def read1(self, size):
        return self.read(size)


def test_pinned_manifest_has_official_version_and_both_verified_native_targets(install) -> None:
    data = json.loads(Path(install.__file__).with_name("releases.json").read_bytes())
    assert data["version"] == "v1.75.2"
    assert data["provenance"]["checksums_sha256"] == (
        "73ede5aab2b8f2dd4b1315f7f063cdd5df10de6338749bba49cbc0c240bda976"
    )
    assert {(item["system"], item["architecture"]) for item in data["releases"]} == {
        ("windows", "amd64"),
        ("linux", "amd64"),
    }
    for item in data["releases"]:
        assert item["url"].startswith("https://downloads.rclone.org/v1.75.2/")
        assert len(item["archive_sha256"]) == len(item["executable_sha256"]) == 64
        assert item["archive_bytes"] > 30_000_000
        assert item["executable_bytes"] > 80_000_000


@pytest.mark.parametrize("machine", ["arm64", "i686", "unknown"])
def test_unsupported_architecture_fails_without_files_or_network(install, monkeypatch, machine):
    monkeypatch.setattr(install, "platform", SimpleNamespace(machine=lambda: machine))
    with pytest.raises(MailCloudError) as failure:
        install.pinned_release()
    assert failure.value.error.kind.value == "backend_unsupported"


@pytest.mark.parametrize(
    "url",
    [
        "http://downloads.rclone.org/x.zip",
        "https://evil.invalid/x.zip",
        "https://downloads.rclone.org.evil.invalid/x.zip",
        "https://user:secret@downloads.rclone.org/x.zip",
        "https://downloads.rclone.org:444/x.zip",
        "https://downloads.rclone.org/x.zip?token=bad",
        "https://downloads.rclone.org/x.zip#fragment",
    ],
)
def test_download_url_policy_rejects_untrusted_routes(install, url):
    with pytest.raises(MailCloudError):
        install._validate_url(url)


def test_offline_archive_is_verified_staged_and_only_then_activated(install, fixture):
    result = install.prepare_rclone(environment=fixture.env, archive=fixture.archive)
    assert result == {
        "dependency": "rclone",
        "status": "installed",
        "source": "managed",
        "version": fixture.release.version,
        "cloud_configured": False,
    }
    path = install.managed_rclone_path(fixture.env)
    assert path is not None and path.read_bytes() == fixture.executable
    assert len(fixture.verified) == 1 and fixture.verified[0] != path
    assert not fixture.verified[0].exists()
    assert not list(fixture.root.glob(".stage-*"))
    assert (Path(fixture.env["RCLONE_CONFIG"])).read_bytes() == b""
    assert Path(fixture.env["HMC_CONFIG"]).read_text() == "[profiles.default]\n"
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o700
        assert stat.S_IMODE(fixture.root.stat().st_mode) == 0o700


def test_repeated_setup_reuses_working_copy_without_download_or_replacement(
    install, fixture, monkeypatch
):
    install.prepare_rclone(environment=fixture.env, archive=fixture.archive)
    path = install.managed_rclone_path(fixture.env)
    identity = path.stat()
    old = (fixture.root / "active.json").read_bytes()
    monkeypatch.setattr(install, "_open_download", lambda *a, **k: pytest.fail("no download"))
    result = install.prepare_rclone(environment=fixture.env)
    assert result["status"] == "already_available" and result["source"] == "managed"
    assert path.stat().st_ino == identity.st_ino
    assert (fixture.root / "active.json").read_bytes() == old
    assert len(fixture.verified) == 1


def test_concurrent_setup_has_one_promotion_and_a_stable_lock(install, fixture):
    start = threading.Barrier(2)

    def setup():
        start.wait(timeout=3)
        return install.prepare_rclone(environment=fixture.env, archive=fixture.archive)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(setup), pool.submit(setup)]
        results = [future.result(timeout=10) for future in futures]
    assert sorted(item["status"] for item in results) == ["already_available", "installed"]
    assert len(fixture.verified) == 1
    assert (fixture.root / ".setup.lock").is_file()
    assert install.managed_rclone_path(fixture.env).read_bytes() == fixture.executable


def test_archive_hash_mismatch_never_executes_or_activates(install, fixture):
    fixture.archive.write_bytes(fixture.payload[:-1] + b"!")
    with pytest.raises(MailCloudError) as failure:
        install.prepare_rclone(environment=fixture.env, archive=fixture.archive)
    assert failure.value.error.kind.value == "parse_error"
    assert not fixture.verified and not (fixture.root / "active.json").exists()
    assert install.managed_rclone_path(fixture.env) is None


@pytest.mark.parametrize("payload", [b"not a zip", b"PK\x03\x04partial"])
def test_corrupt_zip_with_matching_archive_hash_is_rejected(install, fixture, monkeypatch, payload):
    fixture.archive.write_bytes(payload)
    release = replace(
        fixture.release,
        archive_sha256=hashlib.sha256(payload).hexdigest(),
        archive_bytes=len(payload),
    )
    monkeypatch.setattr(install, "pinned_release", lambda: release)
    with pytest.raises(MailCloudError) as failure:
        install.prepare_rclone(environment=fixture.env, archive=fixture.archive)
    assert failure.value.error.kind.value == "parse_error"
    assert not fixture.verified and not (fixture.root / "active.json").exists()


@pytest.mark.parametrize("name", ["../escape", "/escape", "C:/escape", "root/../../escape"])
def test_archive_traversal_or_unexpected_root_is_rejected(install, fixture, monkeypatch, name):
    payload, spec, _ = archive_fixture(fixture.release.system, extra=(name, b"bad"))
    fixture.archive.write_bytes(payload)
    monkeypatch.setattr(install, "pinned_release", lambda: install.Release(**spec))
    with pytest.raises(MailCloudError):
        install.prepare_rclone(environment=fixture.env, archive=fixture.archive)
    assert not fixture.verified and not (fixture.root / "active.json").exists()


def test_archive_symlink_entry_is_rejected(install, fixture, monkeypatch):
    info = zipfile.ZipInfo(f"rclone-{fixture.release.version}-{fixture.release.system}-amd64/link")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    payload, spec, _ = archive_fixture(fixture.release.system, extra=(info, b"rclone"))
    fixture.archive.write_bytes(payload)
    monkeypatch.setattr(install, "pinned_release", lambda: install.Release(**spec))
    with pytest.raises(MailCloudError):
        install.prepare_rclone(environment=fixture.env, archive=fixture.archive)
    assert not fixture.verified


def test_wrong_executable_hash_rejected_before_version_probe(install, fixture, monkeypatch):
    monkeypatch.setattr(
        install, "pinned_release", lambda: replace(fixture.release, executable_sha256="0" * 64)
    )
    with pytest.raises(MailCloudError):
        install.prepare_rclone(environment=fixture.env, archive=fixture.archive)
    assert not fixture.verified


def test_default_https_acquisition_uses_only_pinned_url(install, fixture, monkeypatch):
    requests = []

    def opened(url, *, timeout_seconds):
        assert 0 < timeout_seconds <= 15
        requests.append(url)
        return Response(fixture.payload, url)

    monkeypatch.setattr(install, "_open_download", opened)
    result = install.prepare_rclone(environment=fixture.env)
    assert result["status"] == "installed"
    assert requests == [fixture.release.url]


@pytest.mark.parametrize("route", ["redirect", "oversize", "short", "encoding", "status"])
def test_bad_http_response_does_not_activate(install, fixture, monkeypatch, route):
    response = Response(fixture.payload, fixture.release.url)
    if route == "redirect":
        response.url = "https://evil.invalid/private"
    elif route == "oversize":
        response.headers["Content-Length"] = str(100 * 1024 * 1024)
    elif route == "short":
        response.headers["Content-Length"] = str(len(fixture.payload) - 1)
    elif route == "encoding":
        response.headers["Content-Encoding"] = "gzip"
    else:
        response.status = 404
    monkeypatch.setattr(install, "_open_download", lambda *a, **k: response)
    with pytest.raises(MailCloudError):
        install.prepare_rclone(environment=fixture.env)
    assert response.closed and not fixture.verified
    assert not (fixture.root / "active.json").exists()


def test_network_failure_is_typed_redacted_and_does_not_install(install, fixture, monkeypatch):
    def unavailable(*args, **kwargs):
        raise urllib.error.URLError("R1-SECRET https://user:password@private.invalid")

    monkeypatch.setattr(install, "_open_download", unavailable)
    with pytest.raises(MailCloudError) as failure:
        install.prepare_rclone(environment=fixture.env)
    assert failure.value.error.kind.value == "network_error"
    assert "R1-SECRET" not in str(failure.value) and "private.invalid" not in str(failure.value)
    assert not fixture.verified and not (fixture.root / "active.json").exists()


def test_managed_lookup_does_not_create_missing_storage(install, fixture):
    assert install.managed_rclone_path(fixture.env) is None
    assert not fixture.root.exists()


def test_changed_managed_bytes_are_not_executed_as_a_fallback(install, fixture):
    install.prepare_rclone(environment=fixture.env, archive=fixture.archive)
    path = install.managed_rclone_path(fixture.env)
    path.write_bytes(b"tampered")
    assert install.managed_rclone_path(fixture.env) is None


def test_failed_storage_preflight_does_not_unlink_an_unowned_stage(install, fixture, monkeypatch):
    fixture.root.mkdir(parents=True)
    stage = fixture.root / (".stage-fixed-" + fixture.release.executable_name)
    stage.write_bytes(b"unowned-existing-file")
    monkeypatch.setattr(
        install, "uuid", SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="fixed"))
    )

    def refused(path):
        raise install.PrivateStorageError("synthetic preflight refusal")

    monkeypatch.setattr(
        install, "backend", lambda: SimpleNamespace(ensure_private_directory=refused)
    )
    with pytest.raises(MailCloudError):
        install.prepare_rclone(environment=fixture.env, archive=fixture.archive)
    assert stage.read_bytes() == b"unowned-existing-file"


def test_explicit_missing_path_does_not_download_or_create_managed_storage(install, fixture):
    with pytest.raises(MailCloudError) as failure:
        install.prepare_rclone("missing-explicit", explicit=True, environment=fixture.env)
    assert failure.value.error.kind.value == "rclone_not_found"
    assert not fixture.root.exists() and not fixture.verified


def test_staged_file_hash_is_rechecked_before_any_execution(install, fixture, monkeypatch):
    real = install.backend()

    def corrupted(path, content, *, max_bytes):
        real.atomic_write_replace(path, content, max_bytes=max_bytes)
        if path.name.startswith(".stage-"):
            path.write_bytes(b"corrupted staged executable")

    proxy = SimpleNamespace(
        **{
            name: getattr(real, name)
            for name in (
                "ensure_private_directory",
                "exclusive_lock",
                "assert_private_regular_file",
                "read_private_bytes",
            )
        },
        atomic_write_replace=corrupted,
    )
    monkeypatch.setattr(install, "backend", lambda: proxy)
    monkeypatch.setattr(
        install,
        "_verify_executable",
        lambda *a, **k: pytest.fail("a changed staged executable must not run"),
    )
    with pytest.raises(MailCloudError) as failure:
        install.prepare_rclone(environment=fixture.env, archive=fixture.archive)
    assert failure.value.error.kind.value == "parse_error"
    assert not (fixture.root / "active.json").exists()
    assert not list(fixture.root.glob(".stage-*"))


def test_failed_new_generation_activation_preserves_old_working_bytes_and_pointer(
    install, fixture, monkeypatch
):
    install.prepare_rclone(environment=fixture.env, archive=fixture.archive)
    old_path = install.managed_rclone_path(fixture.env)
    old_bytes = old_path.read_bytes()
    old_pointer = (fixture.root / "active.json").read_bytes()
    candidate = fixture.root / ".stage-next"
    storage = install.backend()
    storage.atomic_write_replace(candidate, fixture.executable, max_bytes=1024)
    if os.name == "posix":
        candidate.chmod(0o700)
    next_release = replace(fixture.release, version="v1.75.3")

    def refused(path, content, *, max_bytes):
        assert path == fixture.root / "active.json"
        raise install.PrivateStorageError("injected activation refusal")

    proxy = SimpleNamespace(
        **{
            name: getattr(storage, name)
            for name in (
                "ensure_private_directory",
                "assert_private_regular_file",
            )
        },
        atomic_write_replace=refused,
    )
    with monkeypatch.context() as patch:
        patch.setattr(install, "backend", lambda: proxy)
        with pytest.raises(install.PrivateStorageError):
            install._activate(fixture.root, candidate, next_release)
    assert old_path.read_bytes() == old_bytes
    assert (fixture.root / "active.json").read_bytes() == old_pointer
    assert install.managed_rclone_path(fixture.env) == old_path


def test_failed_native_version_never_changes_activation_and_removes_owned_stage(
    install, fixture, monkeypatch
):
    def invalid(*args, **kwargs):
        raise MailCloudError(install.ErrorPayload(install.ErrorKind.PARSE_ERROR, "bad version"))

    monkeypatch.setattr(install, "_verify_executable", invalid)
    with pytest.raises(MailCloudError):
        install.prepare_rclone(environment=fixture.env, archive=fixture.archive)
    assert not (fixture.root / "active.json").exists()
    assert not list(fixture.root.glob(".stage-*"))


def test_read_only_default_config_finds_managed_copy_but_explicit_overrides_win(install, fixture):
    from hermes_mailcloud.config import resolve_config

    install.prepare_rclone(environment=fixture.env, archive=fixture.archive)
    managed = install.managed_rclone_path(fixture.env)
    resolved = resolve_config(environment=fixture.env)
    assert resolved.rclone_path == str(managed) and not resolved.rclone_path_explicit
    explicit = str(Path(fixture.env["HOME"]) / "deliberately-missing.exe")
    overridden = resolve_config(environment=fixture.env | {"HMC_RCLONE_PATH": explicit})
    assert overridden.rclone_path == explicit and overridden.rclone_path_explicit
    Path(fixture.env["HMC_CONFIG"]).write_text(
        '[profiles.default]\nrclone_path = "profile-missing"\n', encoding="utf-8"
    )
    profile = resolve_config(environment=fixture.env)
    assert profile.rclone_path == "profile-missing" and profile.rclone_path_explicit


def test_existing_working_external_copy_is_kept_and_not_updated(install, fixture, monkeypatch):
    from hermes_mailcloud.config import resolve_config

    binary = Path(fixture.env["PATH"]) / fixture.release.executable_name
    binary.write_bytes(b"user-owned external rclone")
    if os.name == "posix":
        binary.chmod(0o700)
    monkeypatch.setattr(install, "_verify_executable", lambda *a, **k: "v1.70.0")
    monkeypatch.setattr(install, "_open_download", lambda *a, **k: pytest.fail("no download"))
    assert resolve_config(environment=fixture.env).rclone_path == "rclone"
    result = install.prepare_rclone(environment=fixture.env)
    assert result["status"] == "already_available" and result["source"] == "external"
    assert result["version"] == "v1.70.0"
    assert binary.read_bytes() == b"user-owned external rclone" and not fixture.root.exists()


def test_native_default_external_still_precedes_an_existing_managed_copy(install, fixture):
    from hermes_mailcloud.config import resolve_config

    install.prepare_rclone(environment=fixture.env, archive=fixture.archive)
    external = Path(fixture.env["PATH"]) / fixture.release.executable_name
    external.write_bytes(b"external")
    if os.name == "posix":
        external.chmod(0o700)
    assert resolve_config(environment=fixture.env).rclone_path == "rclone"
    assert install.managed_rclone_path(fixture.env) is not None


def test_setup_deadline_is_single_and_typed_before_network(install, fixture, monkeypatch):
    moments = iter([0.0, 2.0])
    monkeypatch.setattr(install, "time", SimpleNamespace(monotonic=lambda: next(moments)))
    monkeypatch.setattr(install, "_open_download", lambda *a, **k: pytest.fail("no network"))
    with pytest.raises(MailCloudError) as failure:
        install.prepare_rclone(environment=fixture.env, timeout_seconds=1)
    assert failure.value.error.kind.value == "timeout"


def test_current_managed_receipt_survives_a_newer_package_pin_without_auto_update(
    install, fixture, monkeypatch
):
    install.prepare_rclone(environment=fixture.env, archive=fixture.archive)
    old_path = install.managed_rclone_path(fixture.env)
    monkeypatch.setattr(
        install, "pinned_release", lambda: replace(fixture.release, version="v1.75.3")
    )
    monkeypatch.setattr(install, "_open_download", lambda *a, **k: pytest.fail("no update"))
    result = install.prepare_rclone(environment=fixture.env)
    assert result["version"] == fixture.release.version
    assert result["status"] == "already_available"
    assert install.managed_rclone_path(fixture.env) == old_path


def test_https_transport_keeps_certificate_checks_and_no_inherited_proxy_settings(
    install, fixture, monkeypatch
):
    handlers = []
    response = Response(fixture.payload, fixture.release.url)

    def build(*values):
        handlers.extend(values)
        return SimpleNamespace(open=lambda request, timeout: response)

    request = SimpleNamespace(**(vars(install.urllib.request) | {"build_opener": build}))
    monkeypatch.setattr(
        install,
        "urllib",
        SimpleNamespace(request=request, parse=install.urllib.parse, error=install.urllib.error),
    )
    result = install._open_download(fixture.release.url, timeout_seconds=1)
    assert result is response
    https = next(value for value in handlers if isinstance(value, request.HTTPSHandler))
    assert https._context.check_hostname is True
    assert https._context.verify_mode == install.ssl.CERT_REQUIRED
    assert (
        next(value for value in handlers if isinstance(value, request.ProxyHandler)).proxies == {}
    )
    response.close()


def test_version_probe_uses_fresh_real_empty_config_not_a_reserved_device(
    install, monkeypatch, tmp_path
):
    values = environment(tmp_path)
    configs = []

    class Runner:
        def __init__(self, binary, *, environment, max_capture_bytes):
            self.environment = environment

        def run(self, args, *, timeout_seconds):
            config = Path(args[args.index("--config") + 1])
            assert config.is_file() and config.read_bytes() == b""
            assert str(config).casefold() not in {"nul", "/dev/null"}
            assert self.environment["RCLONE_CONFIG"] == str(config)
            configs.append(config)
            return SimpleNamespace(returncode=0, stdout="rclone v1.75.2\n", stdout_truncated=False)

    monkeypatch.setattr(install, "RcloneRunner", Runner)
    assert (
        install._verify_executable(
            tmp_path / "not-executed.exe",
            expected_version="v1.75.2",
            environment=values,
            timeout_seconds=2,
        )
        == "v1.75.2"
    )
    assert configs and not configs[0].parent.exists()

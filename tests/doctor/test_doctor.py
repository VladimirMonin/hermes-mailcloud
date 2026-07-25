"""Fake-backed contracts for read-only and explicitly-confirmed live doctor reports."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hermes_mailcloud.config import ResolvedConfig
from hermes_mailcloud.core.result import ResultEnvelope
from hermes_mailcloud.doctor import DoctorCommands
from hermes_mailcloud.rclone.runner import RcloneResult

_PUBLIC_URL = "https://cloud.mail.ru" + "/public/doctor-fake-capability"


@dataclass
class FakeBackend:
    """A complete deterministic rclone surface for doctor and isolated probe tests."""

    fail_file_cycle: bool = False
    fail_cleanup: bool = False
    unlink_returncode: int = 0
    unlink_stderr: str = ""
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def run(self, args: Sequence[str], *, timeout_seconds: float | None = None) -> RcloneResult:
        del timeout_seconds
        command = tuple(args)
        self.calls.append(command)
        if command == ("version",):
            return _result(stdout="rclone v1.74.3 token=doctor-version-sentinel\n")
        if command == ("listremotes",):
            return _result(stdout="mailru:\n")
        if command in {("lsd", "mailru:"), ("about", "mailru:")}:
            return _result()
        if command[0] == "lsd" and command[1].startswith("mailru:/TEST/"):
            return _result(returncode=3, stderr="directory not found")
        if command[:2] == ("link", "--unlink"):
            return _result(returncode=self.unlink_returncode, stderr=self.unlink_stderr)
        if command[0] == "copyto":
            if self.fail_file_cycle:
                return _result(
                    returncode=17, stderr="network unreachable token=doctor-file-sentinel"
                )
            if command[1].startswith("mailru:"):
                Path(command[2]).write_text("hermes-mailcloud probe\n", encoding="utf-8")
            return _result()
        if command[0] == "link":
            return _result(stdout=f"{_PUBLIC_URL}\n")
        if command[0] == "rmdir" and self.fail_cleanup:
            return _result(returncode=17, stderr="network unreachable")
        if command[0] in {"mkdir", "lsjson", "moveto", "deletefile", "rmdir"}:
            return _result()
        raise AssertionError(f"unexpected fake rclone command: {command!r}")


@dataclass
class FakeHttpResponse:
    status: int
    headers: dict[str, str] = field(default_factory=lambda: {"Content-Type": "text/html"})

    def read(self, size: int) -> bytes:
        return b"x" * size

    def close(self) -> None:
        return None


@dataclass
class SequenceOpener:
    statuses: list[int]
    calls: list[Any] = field(default_factory=list)

    def open(self, request: Any, *, timeout: float) -> FakeHttpResponse:
        self.calls.append((request, timeout))
        return FakeHttpResponse(status=self.statuses.pop(0))


def _result(returncode: int = 0, stdout: str = "", stderr: str = "") -> RcloneResult:
    return RcloneResult(returncode, stdout, stderr, duration_ms=1)


def _config() -> ResolvedConfig:
    return ResolvedConfig(
        profile="test",
        config_path=Path("config.toml"),
        remote="mailru:",
        rclone_path="rclone",
        private_root="/Hermes/private",
        public_root="/Hermes/public",
        temp_root="/Hermes/.tmp",
        links_journal=None,
        default_overwrite="never",
        deny_dangerous_publish=True,
        require_yes_for_destructive=True,
        probe_public_url_after_publish=True,
        timeout_seconds=60,
        retries=0,
    )


def _mapping(value: object) -> Mapping[str, object]:
    assert isinstance(value, dict)
    return value


def test_read_only_doctor_checks_only_safe_rclone_metadata_and_redacts_output() -> None:
    backend = FakeBackend()

    report = DoctorCommands(backend, _config(), timeout_seconds=7).read_only()

    assert report.result == {
        "mode": "read_only",
        "checks": {
            "config_loaded": True,
            "rclone_installed": True,
            "rclone_version": "rclone v1.74.3 token=doctor-version-sentinel",
            "remote_configured": True,
            "remote_listed": True,
            "cloud_access": True,
            "about_available": True,
        },
        "capabilities": {
            "file_ops": "unknown",
            "public_link_create": "unknown",
            "public_link_unlink": "unknown",
        },
    }
    assert backend.calls == [
        ("version",),
        ("listremotes",),
        ("lsd", "mailru:"),
        ("about", "mailru:"),
    ]
    rendered = json.dumps(ResultEnvelope.success("doctor", report.result).to_payload())
    assert "doctor-version-sentinel" not in rendered
    assert "[REDACTED]" in rendered


def test_live_doctor_uses_unique_test_roots_and_marks_unlink_unsupported_only_on_evidence() -> None:
    backend = FakeBackend(unlink_returncode=1, unlink_stderr="backend operation not supported")
    opener = SequenceOpener([200, 200, 404, 200, 200, 404])

    report = DoctorCommands(backend, _config(), timeout_seconds=7, opener=opener).live()

    checks = _mapping(report.result["checks"])
    capabilities = _mapping(report.result["capabilities"])
    roots = report.result["test_roots"]
    assert checks["file_cycle"] is True
    assert checks["public_link_create"] is True
    assert checks["public_url_probe"] is True
    assert checks["unlink_invalidation"] is False
    assert checks["cleanup"] is True
    assert capabilities == {
        "file_ops": "supported",
        "public_link_create": "supported",
        "public_link_unlink": "unsupported",
    }
    assert isinstance(roots, list) and len(roots) == len(set(roots)) == 3
    assert all(
        isinstance(root, str) and root.startswith("/TEST/hermes-mailcloud-") for root in roots
    )
    assert (
        sum(
            call[0] == "lsd" and call[1].startswith("mailru:/TEST/hermes-mailcloud-")
            for call in backend.calls
        )
        == 9
    )
    assert all(
        not any(argument.startswith("mailru:/Hermes") for argument in call)
        for call in backend.calls
    )
    assert all(
        any(argument.startswith("mailru:/TEST/") for argument in call)
        for call in backend.calls
        if call[0] in {"mkdir", "copyto", "moveto", "deletefile", "rmdir", "link"}
    )
    rendered = json.dumps(ResultEnvelope.success("doctor", report.result).to_payload())
    assert _PUBLIC_URL not in rendered
    assert any(
        "not shipped without confirmed public URL invalidation" in warning
        for warning in report.warnings
    )


def test_live_doctor_keeps_failed_and_unknown_capabilities_distinct() -> None:
    backend = FakeBackend(fail_file_cycle=True)

    report = DoctorCommands(backend, _config(), timeout_seconds=7).live()

    checks = _mapping(report.result["checks"])
    assert checks["file_cycle"] is False
    assert checks["cleanup"] is True
    assert _mapping(report.result["capabilities"]) == {
        "file_ops": "failed",
        "public_link_create": "unknown",
        "public_link_unlink": "unknown",
    }
    roots = report.result["test_roots"]
    assert isinstance(roots, list) and len(roots) == 1
    assert not any(call[0] == "link" for call in backend.calls)


def test_live_doctor_stops_before_new_mutations_when_same_run_cleanup_is_not_proven() -> None:
    backend = FakeBackend(fail_cleanup=True)

    report = DoctorCommands(backend, _config(), timeout_seconds=7).live()

    checks = _mapping(report.result["checks"])
    capabilities = _mapping(report.result["capabilities"])
    assert checks["file_cycle"] is True
    assert checks["cleanup"] is False
    assert capabilities == {
        "file_ops": "supported",
        "public_link_create": "unknown",
        "public_link_unlink": "unknown",
    }
    assert report.result["test_roots"] and not any(call[0] == "link" for call in backend.calls)
    assert "live checks stopped because same-run cleanup was not proven" in report.warnings

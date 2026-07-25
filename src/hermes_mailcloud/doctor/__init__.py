"""Read-only and explicitly-confirmed live diagnostics for the Mail.ru backend."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

from ..config import ResolvedConfig
from ..core.errors import ErrorKind
from ..probes.core import (
    CommandResult,
    HttpOpener,
    ProbeOutcome,
    generate_test_root,
    run_file_ops_probe,
    run_publish_probe,
    run_unlink_probe,
)
from ..rclone.runner import RcloneResult, RcloneRunnerError, map_rclone_error

Capability = Literal["unknown", "supported", "unsupported", "failed"]

_FILE_CYCLE_CHECKS = frozenset(
    {"root_absent", "mkdir", "upload", "list", "download", "content_match", "move", "delete"}
)


class DiagnosticBackend(Protocol):
    """The safe, bounded rclone runner surface used by doctor diagnostics."""

    def run(self, args: Sequence[str], *, timeout_seconds: float | None = None) -> RcloneResult:
        """Run one literal read-only or already-authorized probe command."""
        ...


@dataclass(frozen=True, slots=True)
class DiagnosticCall:
    """A redaction-safe classification of one diagnostic backend call."""

    ok: bool
    stdout: str = ""
    error_kind: ErrorKind | None = None


@dataclass(frozen=True, slots=True)
class DoctorReport:
    """Schema-shaped doctor result plus safe, human-readable warnings."""

    result: dict[str, object]
    warnings: tuple[str, ...] = ()


@dataclass(slots=True)
class _ProbeBackend:
    """Adapt the typed runner to the isolated probe protocol without exposing output."""

    backend: DiagnosticBackend
    timeout_seconds: float
    invocations: list[tuple[tuple[str, ...], ErrorKind | None]] = field(default_factory=list)

    def run(self, args: list[str], *, timeout: float | None = None) -> CommandResult:
        effective_timeout = (
            self.timeout_seconds if timeout is None else min(timeout, self.timeout_seconds)
        )
        try:
            result = self.backend.run(args, timeout_seconds=effective_timeout)
        except RcloneRunnerError as exc:
            self.invocations.append((tuple(args), exc.error.kind))
            return CommandResult(returncode=1, stdout="", stderr=exc.error.message)

        error_kind = map_rclone_error(result).kind if result.returncode else None
        self.invocations.append((tuple(args), error_kind))
        return CommandResult(result.returncode, result.stdout, result.stderr)

    def error_kind_for(self, *prefix: str) -> ErrorKind | None:
        for args, error_kind in reversed(self.invocations):
            if args[: len(prefix)] == prefix:
                return error_kind
        return None

    def invoked(self, *prefix: str) -> bool:
        return any(args[: len(prefix)] == prefix for args, _ in self.invocations)


@dataclass(frozen=True, slots=True)
class DoctorCommands:
    """Run only read diagnostics by default and bounded probes after explicit confirmation."""

    backend: DiagnosticBackend
    config: ResolvedConfig
    timeout_seconds: float
    retries: int = 0
    opener: HttpOpener | None = None

    def __post_init__(self) -> None:
        if isinstance(self.timeout_seconds, bool) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if isinstance(self.retries, bool) or self.retries < 0:
            raise ValueError("retries must be non-negative")

    def read_only(self) -> DoctorReport:
        """Check local rclone configuration and cloud metadata without mutating the remote."""
        checks: dict[str, object] = {
            "config_loaded": True,
            "rclone_installed": False,
            "rclone_version": None,
            "remote_configured": self.config.remote is not None,
            "remote_listed": False,
            "cloud_access": False,
            "about_available": False,
        }
        warnings: list[str] = []

        version = self._call(("version",))
        if not version.ok:
            warnings.append("rclone version check did not succeed; remote checks were skipped")
            return DoctorReport(self._result("read_only", checks), tuple(warnings))

        checks["rclone_installed"] = True
        checks["rclone_version"] = _version_line(version.stdout)
        if self.config.remote is None:
            warnings.append("no rclone remote is configured; cloud checks were skipped")
            return DoctorReport(self._result("read_only", checks), tuple(warnings))

        listed = self._call(("listremotes",))
        if not listed.ok:
            warnings.append("rclone remote listing did not succeed; cloud checks were skipped")
            return DoctorReport(self._result("read_only", checks), tuple(warnings))

        checks["remote_listed"] = self.config.remote in {
            line.strip() for line in listed.stdout.splitlines()
        }
        if not checks["remote_listed"]:
            warnings.append("configured rclone remote was not listed; cloud checks were skipped")
            return DoctorReport(self._result("read_only", checks), tuple(warnings))

        cloud_access = self._call(("lsd", self.config.remote))
        checks["cloud_access"] = cloud_access.ok
        about = self._call(("about", self.config.remote))
        checks["about_available"] = about.ok
        if not cloud_access.ok:
            warnings.append("read-only cloud listing did not succeed")
        if not about.ok:
            warnings.append("rclone about was unavailable; list access was still checked")
        return DoctorReport(self._result("read_only", checks), tuple(warnings))

    def live(self) -> DoctorReport:
        """Run generated `/TEST` probes only after the CLI has confirmed live intent."""
        read_only = self.read_only()
        result = dict(read_only.result)
        base_checks = result["checks"]
        if not isinstance(base_checks, dict):
            raise AssertionError("read-only doctor report must contain checks")
        checks: dict[str, object] = {str(name): value for name, value in base_checks.items()}
        checks.update(
            {
                "file_cycle": False,
                "public_link_create": False,
                "public_url_probe": False,
                "unlink_invalidation": False,
                "cleanup": False,
            }
        )
        capabilities: dict[str, Capability] = {
            "file_ops": "unknown",
            "public_link_create": "unknown",
            "public_link_unlink": "unknown",
        }
        warnings = list(read_only.warnings)
        test_roots: list[str] = []

        if not _readiness_allows_live(checks):
            warnings.append("live checks were not run because read-only readiness did not pass")
            return DoctorReport(
                {
                    "mode": "live",
                    "test_roots": test_roots,
                    "checks": checks,
                    "capabilities": capabilities,
                },
                tuple(warnings),
            )

        assert self.config.remote is not None
        file_probe = _ProbeBackend(self.backend, self.timeout_seconds)
        file_root = generate_test_root()
        test_roots.append(file_root)
        file_outcome = run_file_ops_probe(
            remote=self.config.remote,
            root=file_root,
            runner=file_probe,
            live_enabled=True,
        )
        checks["file_cycle"] = _has_all_checks(file_outcome, _FILE_CYCLE_CHECKS)
        capabilities["file_ops"] = _capability_from_outcome(
            file_outcome, file_probe, command_prefixes=(("mkdir",), ("copyto",), ("moveto",))
        )
        _append_outcome_warning(warnings, "file-cycle", file_outcome)
        cleanup_outcomes = [file_outcome]

        if not self._cleanup_proven(cleanup_outcomes, test_roots):
            checks["cleanup"] = False
            warnings.append("live checks stopped because same-run cleanup was not proven")
            return DoctorReport(
                {
                    "mode": "live",
                    "test_roots": test_roots,
                    "checks": checks,
                    "capabilities": capabilities,
                },
                tuple(warnings),
            )

        if capabilities["file_ops"] != "supported":
            warnings.append("public-link checks were skipped because the file cycle was not proven")
            checks["cleanup"] = True
            return DoctorReport(
                {
                    "mode": "live",
                    "test_roots": test_roots,
                    "checks": checks,
                    "capabilities": capabilities,
                },
                tuple(warnings),
            )

        public_probe = _ProbeBackend(self.backend, self.timeout_seconds)
        public_root = generate_test_root()
        test_roots.append(public_root)
        public_outcome = run_publish_probe(
            remote=self.config.remote,
            root=public_root,
            runner=public_probe,
            live_enabled=True,
            opener=self.opener,
        )
        checks["public_link_create"] = public_outcome.checks.get("link_create") is True
        checks["public_url_probe"] = public_outcome.checks.get("public_url_probe") is True
        capabilities["public_link_create"] = _capability_from_outcome(
            public_outcome, public_probe, command_prefixes=(("link",),)
        )
        _append_outcome_warning(warnings, "public-link", public_outcome)
        cleanup_outcomes.append(public_outcome)

        if not self._cleanup_proven(cleanup_outcomes, test_roots):
            checks["cleanup"] = False
            warnings.append("live checks stopped because same-run cleanup was not proven")
            return DoctorReport(
                {
                    "mode": "live",
                    "test_roots": test_roots,
                    "checks": checks,
                    "capabilities": capabilities,
                },
                tuple(warnings),
            )

        if capabilities["public_link_create"] != "supported":
            warnings.append(
                "unlink checks were skipped because public link creation was not proven"
            )
            checks["cleanup"] = True
            return DoctorReport(
                {
                    "mode": "live",
                    "test_roots": test_roots,
                    "checks": checks,
                    "capabilities": capabilities,
                },
                tuple(warnings),
            )

        unlink_probe = _ProbeBackend(self.backend, self.timeout_seconds)
        unlink_root = generate_test_root()
        test_roots.append(unlink_root)
        unlink_outcome = run_unlink_probe(
            remote=self.config.remote,
            root=unlink_root,
            runner=unlink_probe,
            live_enabled=True,
            opener=self.opener,
        )
        checks["unlink_invalidation"] = unlink_outcome.checks.get("public_url_invalidated") is True
        capabilities["public_link_unlink"] = _unlink_capability(unlink_outcome, unlink_probe)
        _append_outcome_warning(warnings, "unlink", unlink_outcome)
        cleanup_outcomes.append(unlink_outcome)
        checks["cleanup"] = self._cleanup_proven(cleanup_outcomes, test_roots)

        if capabilities["public_link_unlink"] == "unsupported":
            warnings.append("unlink is not shipped without confirmed public URL invalidation")
        return DoctorReport(
            {
                "mode": "live",
                "test_roots": test_roots,
                "checks": checks,
                "capabilities": capabilities,
            },
            tuple(warnings),
        )

    def _result(
        self, mode: Literal["read_only", "live"], checks: dict[str, object]
    ) -> dict[str, object]:
        return {
            "mode": mode,
            "checks": checks,
            "capabilities": {
                "file_ops": "unknown",
                "public_link_create": "unknown",
                "public_link_unlink": "unknown",
            },
        }

    def _verify_cleanup(self, roots: Sequence[str]) -> bool:
        """Prove every allocated test root is absent after its same-run cleanup."""
        assert self.config.remote is not None
        return all(
            self._call(("lsd", f"{self.config.remote}{root}")).error_kind is ErrorKind.NOT_FOUND
            for root in roots
        )

    def _cleanup_proven(self, outcomes: list[ProbeOutcome], roots: Sequence[str]) -> bool:
        """Require both probe-accounted cleanup and an absent-root read-back before continuing."""
        return _cleanup_complete(outcomes) and self._verify_cleanup(roots)

    def _call(self, args: Sequence[str]) -> DiagnosticCall:
        for attempt in range(self.retries + 1):
            try:
                result = self.backend.run(args, timeout_seconds=self.timeout_seconds)
            except RcloneRunnerError as exc:
                error_kind = exc.error.kind
                stdout = ""
            else:
                if result.returncode == 0:
                    return DiagnosticCall(ok=True, stdout=result.stdout)
                error_kind = map_rclone_error(result).kind
                stdout = ""
            if (
                error_kind not in {ErrorKind.NETWORK_ERROR, ErrorKind.TIMEOUT}
                or attempt == self.retries
            ):
                return DiagnosticCall(ok=False, error_kind=error_kind, stdout=stdout)
        raise AssertionError("diagnostic retry loop must return")


def _version_line(stdout: str) -> str | None:
    line = next((item.strip() for item in stdout.splitlines() if item.strip()), "")
    return line[:256] or None


def _readiness_allows_live(checks: dict[str, object]) -> bool:
    return all(
        checks.get(name) is True
        for name in ("rclone_installed", "remote_configured", "remote_listed", "cloud_access")
    )


def _has_all_checks(outcome: ProbeOutcome, names: frozenset[str]) -> bool:
    return all(outcome.checks.get(name) is True for name in names)


def _capability_from_outcome(
    outcome: ProbeOutcome,
    probe: _ProbeBackend,
    *,
    command_prefixes: tuple[tuple[str, ...], ...],
) -> Capability:
    if outcome.ok or _has_successful_probe_call(outcome, command_prefixes):
        return "supported"
    if any(
        probe.error_kind_for(*prefix) is ErrorKind.BACKEND_UNSUPPORTED
        for prefix in command_prefixes
    ):
        return "unsupported"
    return "failed"


def _has_successful_probe_call(
    outcome: ProbeOutcome, command_prefixes: tuple[tuple[str, ...], ...]
) -> bool:
    if ("link",) in command_prefixes:
        return outcome.checks.get("link_create") is True
    return _has_all_checks(outcome, _FILE_CYCLE_CHECKS)


def _unlink_capability(outcome: ProbeOutcome, probe: _ProbeBackend) -> Capability:
    if outcome.checks.get("public_url_invalidated") is True:
        return "supported"
    if probe.error_kind_for("link", "--unlink") is ErrorKind.BACKEND_UNSUPPORTED:
        return "unsupported"
    if probe.invoked("link", "--unlink"):
        if outcome.checks.get("unlink_command") is True:
            return "unsupported"
        return "failed"
    return "failed"


def _cleanup_complete(outcomes: list[ProbeOutcome]) -> bool:
    return all(
        outcome.cleanup is None or outcome.cleanup.get("complete") is True for outcome in outcomes
    )


def _append_outcome_warning(warnings: list[str], name: str, outcome: ProbeOutcome) -> None:
    if not outcome.ok:
        kind = outcome.error.get("kind") if outcome.error else "unknown"
        warnings.append(f"{name} check did not complete ({kind})")
    warnings.extend(f"{name}: {warning}" for warning in outcome.warnings)

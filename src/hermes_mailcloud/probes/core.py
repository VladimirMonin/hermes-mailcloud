"""Reusable safety boundary for opt-in Mail.ru Cloud capability probes.

The probe layer is deliberately separate from the future product CLI. It owns
only generated `/TEST/hermes-mailcloud-*` roots, never emits raw provider output
or public URLs, and can be driven entirely by fake runners in offline tests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import secrets
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn, Protocol, TextIO, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_HTTP_BODY_BYTES = 8 * 1024
MAX_HTTP_REDIRECTS = 3
RCLONE_TIMEOUT_SECONDS = 30.0
PUBLIC_HOST = "cloud.mail.ru"
REMOTE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}:$")
RUN_ID_PATTERN = re.compile(r"^hermes-mailcloud-\d{8}T\d{6}Z-[a-f0-9]{8}$", re.IGNORECASE)
PUBLIC_URL_PATTERN = re.compile(r"https://cloud\.mail\.ru/public/[^\s'\"<>]+", re.IGNORECASE)
SENSITIVE_KEY_NAME_PATTERN = re.compile(
    r"(?i)^(access[_-]?token|refresh[_-]?token|api[_-]?key|password|passwd|secret|token|cookie|authorization)$"
)
SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"""(?ix)
    (?P<prefix>
        [\"']?(?:access[_-]?token|refresh[_-]?token|api[_-]?key|password|passwd|secret|token|cookie|authorization)[\"']?
        \s*[:=]\s*
    )
    (?P<value>
        \"(?:\\.|[^\"\\])*\"
        | '(?:\\.|[^'\\])*'
        | [^\s,;}\]]+
    )
    """
)
ESCAPED_SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"""(?ix)
    (?P<prefix>
        \\+[\"'](?:access[_-]?token|refresh[_-]?token|api[_-]?key|password|passwd|secret|token|cookie|authorization)\\+[\"']
        \s*[:=]\s*\\+[\"']
    )
    (?P<value>[^\r\n]*?)
    (?P<suffix>\\+[\"'])
    (?=\s*(?:[,;}\]]|$))
    """
)
AUTHORIZATION_PATTERN = re.compile(r"(?i)(\bauthorization\s*:\s*)(?:bearer\s+)?[^\s,;]+")
BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[^\s,;]+")
MAX_PRIVATE_INPUT_BYTES = 4 * 1024


@dataclass(frozen=True)
class CommandResult:
    """Sanitizable subprocess result used by real and fake runners."""

    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    """Minimal runner surface that makes probes independently testable."""

    def run(self, args: list[str], *, timeout: float | None = None) -> CommandResult:
        """Run an rclone subcommand without a shell."""
        ...


class HttpOpener(Protocol):
    """Small HTTP seam for bounded local tests."""

    def open(self, request: Request, *, timeout: float) -> Any:
        """Open one request."""


class SubprocessRcloneRunner:
    """Run a validated rclone command with no shell interpolation."""

    def __init__(self, binary: str = "rclone") -> None:
        self._binary = binary

    def run(self, args: list[str], *, timeout: float | None = None) -> CommandResult:
        completed = subprocess.run(
            [self._binary, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout or RCLONE_TIMEOUT_SECONDS,
        )
        return CommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


@dataclass
class ProbeOutcome:
    """A report-shaped result that can be emitted on both success and failure."""

    ok: bool
    checks: dict[str, bool] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    cleanup: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": self.ok,
            "checks": self.checks,
            "result": self.result,
            "warnings": self.warnings,
        }
        if self.cleanup is not None:
            payload["cleanup"] = self.cleanup
        if self.error is not None:
            payload["error"] = self.error
        return payload


@dataclass
class ProbeFailure(Exception):
    """Expected failure whose message and details are safe to serialize."""

    kind: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"kind": self.kind, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


@dataclass
class PublicCapability:
    """An in-memory only public link that must be invalidated before cleanup is complete."""

    path: str
    public_url: str
    invalidated: bool = False


@dataclass
class CleanupManifest:
    """Account only for paths and capabilities that this generated run created."""

    root: str
    root_created: bool = False
    active_files: list[str] = field(default_factory=list)
    public_capabilities: list[PublicCapability] = field(default_factory=list)
    removed_count: int = 0
    failures: list[dict[str, Any]] = field(default_factory=list)
    root_removed: bool = False

    def register_root(self) -> None:
        self.root_created = True

    def register_file(self, path: str) -> None:
        if not _is_descendant(path, self.root):
            raise ValueError("cleanup can only register paths inside the generated test root")
        self.active_files.append(path)

    def register_public_capability(self, path: str, public_url: str) -> None:
        if path not in self.active_files:
            raise ValueError("public capability must belong to an active generated file")
        self.public_capabilities.append(PublicCapability(path=path, public_url=public_url))

    def rename_file(self, old_path: str, new_path: str) -> None:
        if old_path not in self.active_files or not _is_descendant(new_path, self.root):
            raise ValueError("cleanup manifest cannot leave the generated test root")
        self.active_files.remove(old_path)
        self.active_files.append(new_path)
        for capability in self.public_capabilities:
            if capability.path == old_path:
                capability.path = new_path

    def mark_removed(self, path: str) -> None:
        if path in self.active_files:
            self.active_files.remove(path)
            self.removed_count += 1

    def mark_public_capability_invalidated(self, public_url: str) -> None:
        for capability in self.public_capabilities:
            if capability.public_url == public_url:
                capability.invalidated = True
                return
        raise ValueError("cleanup manifest does not own this public capability")

    def cleanup(
        self, runner: CommandRunner, remote: str, *, opener: HttpOpener | None = None
    ) -> None:
        for path in reversed(self.active_files.copy()):
            result = _runner_result(runner, ["deletefile", qualified_remote_path(remote, path)])
            if result.returncode == 0:
                self.mark_removed(path)
            else:
                self.failures.append(
                    {
                        "action": "deletefile",
                        "exit_code": result.returncode,
                        "stderr_tail": _safe_tail(result.stderr),
                    }
                )

        if self.root_created and not self.active_files and not self.failures:
            result = _runner_result(runner, ["rmdir", qualified_remote_path(remote, self.root)])
            if result.returncode == 0:
                self.root_removed = True
            else:
                self.failures.append(
                    {
                        "action": "rmdir",
                        "exit_code": result.returncode,
                        "stderr_tail": _safe_tail(result.stderr),
                    }
                )

        self._verify_public_capabilities(opener)

    def _verify_public_capabilities(self, opener: HttpOpener | None) -> None:
        active_opener = cast(HttpOpener, opener or build_opener(_NoRedirectHandler()))
        for capability in self.public_capabilities:
            if capability.invalidated:
                continue
            fingerprint = _public_url_fingerprint(capability.public_url)
            if capability.path in self.active_files:
                self.failures.append(
                    {
                        "action": "public_url_invalidation",
                        "public_url_fingerprint": fingerprint,
                        "message": "generated file deletion did not complete",
                    }
                )
                continue
            try:
                post_delete = _bounded_http_request(
                    active_opener, capability.public_url, method="GET", read_body=True
                )
            except ProbeFailure:
                self.failures.append(
                    {
                        "action": "public_url_invalidation",
                        "public_url_fingerprint": fingerprint,
                        "message": "could not verify public capability invalidation",
                    }
                )
                continue
            if post_delete["status_code"] in {404, 410}:
                capability.invalidated = True
                continue
            self.failures.append(
                {
                    "action": "public_url_invalidation",
                    "public_url_fingerprint": fingerprint,
                    "status_code": post_delete["status_code"],
                }
            )

    def to_payload(self) -> dict[str, Any]:
        unresolved = sorted(
            _public_url_fingerprint(capability.public_url)
            for capability in self.public_capabilities
            if not capability.invalidated
        )
        complete = (
            not self.active_files
            and not self.failures
            and not unresolved
            and (not self.root_created or self.root_removed)
        )
        return {
            "root": self.root,
            "created_file_count": self.removed_count + len(self.active_files),
            "removed_file_count": self.removed_count,
            "remaining_file_count": len(self.active_files),
            "public_capability_count": len(self.public_capabilities),
            "invalidated_public_capability_count": len(self.public_capabilities) - len(unresolved),
            "unresolved_public_capability_fingerprints": unresolved,
            "root_removed": self.root_removed,
            "failure_count": len(self.failures),
            "complete": complete,
        }


def redact_text(value: str) -> str:
    """Redact credentials and replace public URLs with non-reversible fingerprints."""

    def redact_url(match: re.Match[str]) -> str:
        digest = hashlib.sha256(match.group(0).encode("utf-8")).hexdigest()
        return f"[public-url sha256:{digest}]"

    redacted = PUBLIC_URL_PATTERN.sub(redact_url, value)
    redacted = ESCAPED_SENSITIVE_ASSIGNMENT_PATTERN.sub(r"\g<prefix>[REDACTED]\g<suffix>", redacted)
    redacted = AUTHORIZATION_PATTERN.sub(r"\1[REDACTED]", redacted)
    redacted = BEARER_PATTERN.sub("Bearer [REDACTED]", redacted)
    return SENSITIVE_ASSIGNMENT_PATTERN.sub(r"\g<prefix>[REDACTED]", redacted)


def sanitize_value(value: Any) -> Any:
    """Recursively apply output redaction before JSON emission or artifact writes."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_value(item) for item in value]
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if _is_sensitive_mapping_key(str(key)) else sanitize_value(item)
            for key, item in value.items()
        }
    return value


def _is_sensitive_mapping_key(key: str) -> bool:
    return SENSITIVE_KEY_NAME_PATTERN.fullmatch(key.strip()) is not None


def validate_remote(remote: str) -> str:
    """Accept remote identifiers only, never rclone connection strings or credentials."""
    if not REMOTE_PATTERN.fullmatch(remote):
        raise ValueError("remote must be a simple rclone remote name ending in ':'")
    return remote


def validate_test_root(root: str) -> str:
    """Require one generated direct child of /TEST with no normalization ambiguity."""
    normalized = posixpath.normpath(root)
    if root != normalized:
        raise ValueError("test root must already be normalized")
    parts = normalized.split("/")
    if len(parts) != 3 or parts[0] or parts[1] != "TEST" or not RUN_ID_PATTERN.fullmatch(parts[2]):
        raise ValueError("test root must be /TEST/hermes-mailcloud-<unique-run-id>")
    return normalized


def generate_test_root() -> str:
    """Generate the only default cloud root accepted for mutating probes."""
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"/TEST/hermes-mailcloud-{timestamp}-{secrets.token_hex(4)}"


def resolve_test_root(value: str | None) -> str:
    """Validate a supplied root or generate an isolated root for this process."""
    return validate_test_root(value) if value else generate_test_root()


def qualified_remote_path(remote: str, cloud_path: str) -> str:
    """Join already-validated pieces into the only rclone remote-path form used here."""
    validate_remote(remote)
    if not cloud_path.startswith("/"):
        raise ValueError("cloud path must be absolute")
    return f"{remote}{cloud_path}"


def run_env_probe(*, remote: str, runner: CommandRunner) -> ProbeOutcome:
    """Read-only rclone and remote readiness evidence."""
    checks: dict[str, bool] = {}
    warnings: list[str] = []
    try:
        remote = validate_remote(remote)
        version = _require_success(runner, "rclone_installed", ["version"])
        checks["rclone_installed"] = True
        remotes = _require_success(runner, "remote_list", ["listremotes"])
        checks["remote_exists"] = remote in {line.strip() for line in remotes.stdout.splitlines()}
        if not checks["remote_exists"]:
            raise ProbeFailure("remote_not_found", "configured remote was not listed")
        _require_success(runner, "cloud_access", ["lsd", remote])
        checks["cloud_access"] = True
        about = _runner_result(runner, ["about", remote])
        checks["about_available"] = about.returncode == 0
        if not checks["about_available"]:
            warnings.append("rclone about was unavailable; core read-only access was still checked")
        version_line = (
            redact_text(version.stdout.strip().splitlines()[0]) if version.stdout.strip() else ""
        )
        return ProbeOutcome(
            ok=True,
            checks=checks,
            result={"remote": remote, "rclone_version": version_line},
            warnings=warnings,
        )
    except ProbeFailure as failure:
        return ProbeOutcome(ok=False, checks=checks, warnings=warnings, error=failure.to_payload())
    except ValueError:
        return _invalid_input_outcome()


def run_file_ops_probe(
    *, remote: str, root: str, runner: CommandRunner, live_enabled: bool
) -> ProbeOutcome:
    """Run a self-contained file lifecycle and account for every same-run cleanup action."""
    if not live_enabled:
        return ProbeOutcome(
            ok=False,
            error={
                "kind": "live_not_enabled",
                "message": "set HMC_LIVE=1 before a mutating probe can run",
            },
        )

    checks: dict[str, bool] = {}
    manifest: CleanupManifest | None = None
    failure: ProbeFailure | None = None
    try:
        remote = validate_remote(remote)
        root = validate_test_root(root)
        manifest = CleanupManifest(root=root)
        root_target = qualified_remote_path(remote, root)
        preflight = _runner_result(runner, ["lsd", root_target])
        if preflight.returncode == 0:
            raise ProbeFailure("test_root_exists", "generated test root already exists")
        if not _indicates_missing_path(preflight.stderr):
            raise ProbeFailure(
                "test_root_absence_unproven",
                "could not prove that the generated test root is absent",
                {"exit_code": preflight.returncode, "stderr_tail": _safe_tail(preflight.stderr)},
            )
        checks["root_absent"] = True
        _require_success(runner, "mkdir", ["mkdir", root_target])
        checks["mkdir"] = True
        manifest.register_root()

        with tempfile.TemporaryDirectory(prefix="hmc-probe-") as temp_dir:
            local_dir = Path(temp_dir)
            source = local_dir / "source.txt"
            downloaded = local_dir / "downloaded.txt"
            source.write_text("hermes-mailcloud probe\n", encoding="utf-8")
            uploaded_path = f"{root}/hmc-file-ops.txt"
            renamed_path = f"{root}/hmc-file-ops-renamed.txt"
            uploaded_target = qualified_remote_path(remote, uploaded_path)
            renamed_target = qualified_remote_path(remote, renamed_path)

            _require_success(runner, "upload", ["copyto", str(source), uploaded_target])
            checks["upload"] = True
            manifest.register_file(uploaded_path)
            _require_success(runner, "list", ["lsjson", root_target])
            checks["list"] = True
            _require_success(runner, "download", ["copyto", uploaded_target, str(downloaded)])
            checks["download"] = True
            if not downloaded.exists():
                raise ProbeFailure(
                    "download_missing", "rclone did not create the expected local download"
                )
            checks["content_match"] = downloaded.read_bytes() == source.read_bytes()
            if not checks["content_match"]:
                raise ProbeFailure(
                    "download_mismatch", "downloaded file did not match the generated source"
                )
            _require_success(runner, "move", ["moveto", uploaded_target, renamed_target])
            checks["move"] = True
            manifest.rename_file(uploaded_path, renamed_path)
            _require_success(runner, "delete", ["deletefile", renamed_target])
            checks["delete"] = True
            manifest.mark_removed(renamed_path)
    except ProbeFailure as caught:
        failure = caught
    except ValueError:
        failure = ProbeFailure("invalid_input", "probe input did not pass the safety policy")
    except OSError:
        failure = ProbeFailure(
            "local_io_failed", "generated local probe data could not be prepared"
        )
    finally:
        if manifest is not None:
            manifest.cleanup(runner, remote)

    cleanup = manifest.to_payload() if manifest is not None else None
    if failure is None and cleanup is not None and not cleanup["complete"]:
        failure = ProbeFailure("cleanup_failed", "same-run cleanup did not complete", cleanup)
    return ProbeOutcome(
        ok=failure is None,
        checks=checks,
        result={"remote": remote, "root": root} if manifest is not None else {},
        cleanup=cleanup,
        error=failure.to_payload() if failure is not None else None,
    )


def run_publish_probe(
    *,
    remote: str,
    root: str,
    runner: CommandRunner,
    live_enabled: bool,
    opener: HttpOpener | None = None,
) -> ProbeOutcome:
    """Create a public link, inspect it through the allowlist, and clean up only same-run data."""
    if not live_enabled:
        return _live_not_enabled_outcome()

    checks: dict[str, bool] = {}
    manifest: CleanupManifest | None = None
    failure: ProbeFailure | None = None
    result: dict[str, Any] = {}
    try:
        remote = validate_remote(remote)
        root = validate_test_root(root)
        manifest = CleanupManifest(root=root)
        root_target = qualified_remote_path(remote, root)
        _prove_root_is_absent(runner, root_target)
        checks["root_absent"] = True
        _require_success(runner, "mkdir", ["mkdir", root_target])
        checks["mkdir"] = True
        manifest.register_root()
        with tempfile.TemporaryDirectory(prefix="hmc-probe-") as temp_dir:
            source = Path(temp_dir) / "public.txt"
            source.write_text("hermes-mailcloud public probe\n", encoding="utf-8")
            cloud_path = f"{root}/hmc-public-probe.txt"
            cloud_target = qualified_remote_path(remote, cloud_path)
            _require_success(runner, "upload", ["copyto", str(source), cloud_target])
            checks["upload"] = True
            manifest.register_file(cloud_path)
            linked = _require_success(runner, "link_create", ["link", cloud_target])
            checks["link_create"] = True
            public_url = _extract_public_url(linked.stdout)
            manifest.register_public_capability(cloud_path, public_url)
            http_result = probe_public_url(public_url, opener=opener)
            checks["public_url_probe"] = True
            result = {"remote": remote, "root": root, **http_result}
    except ProbeFailure as caught:
        failure = caught
    except ValueError:
        failure = ProbeFailure("invalid_input", "probe input did not pass the safety policy")
    except OSError:
        failure = ProbeFailure(
            "local_io_failed", "generated local probe data could not be prepared"
        )
    finally:
        if manifest is not None:
            manifest.cleanup(runner, remote, opener=opener)

    return _outcome_with_cleanup(checks, result, manifest, failure)


def run_unlink_probe(
    *,
    remote: str,
    root: str,
    runner: CommandRunner,
    live_enabled: bool,
    opener: HttpOpener | None = None,
) -> ProbeOutcome:
    """Measure whether rclone unlink also produces an observable public-link invalidation."""
    if not live_enabled:
        return _live_not_enabled_outcome()

    checks: dict[str, bool] = {}
    warnings: list[str] = []
    manifest: CleanupManifest | None = None
    failure: ProbeFailure | None = None
    result: dict[str, Any] = {}
    try:
        remote = validate_remote(remote)
        root = validate_test_root(root)
        manifest = CleanupManifest(root=root)
        root_target = qualified_remote_path(remote, root)
        _prove_root_is_absent(runner, root_target)
        checks["root_absent"] = True
        _require_success(runner, "mkdir", ["mkdir", root_target])
        checks["mkdir"] = True
        manifest.register_root()
        with tempfile.TemporaryDirectory(prefix="hmc-probe-") as temp_dir:
            source = Path(temp_dir) / "unlink.txt"
            source.write_text("hermes-mailcloud unlink probe\n", encoding="utf-8")
            cloud_path = f"{root}/hmc-unlink-probe.txt"
            cloud_target = qualified_remote_path(remote, cloud_path)
            _require_success(runner, "upload", ["copyto", str(source), cloud_target])
            checks["upload"] = True
            manifest.register_file(cloud_path)
            linked = _require_success(runner, "link_create", ["link", cloud_target])
            checks["link_create"] = True
            public_url = _extract_public_url(linked.stdout)
            manifest.register_public_capability(cloud_path, public_url)
            probe_public_url(public_url, opener=opener)
            checks["public_url_before_unlink"] = True
            unlink = _runner_result(runner, ["link", "--unlink", cloud_target])
            checks["unlink_command"] = unlink.returncode == 0
            if unlink.returncode != 0:
                warnings.append("rclone link --unlink did not report support for this backend")
                result = {
                    "remote": remote,
                    "root": root,
                    "public_url_fingerprint": _public_url_fingerprint(public_url),
                    "unlink_supported": False,
                }
            else:
                active_opener = cast(HttpOpener, opener or build_opener(_NoRedirectHandler()))
                post_unlink = _bounded_http_request(
                    active_opener, public_url, method="GET", read_body=True
                )
                invalidated = post_unlink["status_code"] in {404, 410}
                checks["public_url_invalidated"] = invalidated
                if invalidated:
                    manifest.mark_public_capability_invalidated(public_url)
                else:
                    warnings.append(
                        "unlink command completed but the public URL was still reachable"
                    )
                result = {
                    "remote": remote,
                    "root": root,
                    "public_url_fingerprint": _public_url_fingerprint(public_url),
                    "unlink_supported": invalidated,
                    "post_unlink_status_code": post_unlink["status_code"],
                }
    except ProbeFailure as caught:
        failure = caught
    except ValueError:
        failure = ProbeFailure("invalid_input", "probe input did not pass the safety policy")
    except OSError:
        failure = ProbeFailure(
            "local_io_failed", "generated local probe data could not be prepared"
        )
    finally:
        if manifest is not None:
            manifest.cleanup(runner, remote, opener=opener)

    outcome = _outcome_with_cleanup(checks, result, manifest, failure)
    outcome.warnings.extend(warnings)
    return outcome


def run_public_url_probe(*, public_url: str, opener: HttpOpener | None = None) -> ProbeOutcome:
    """Perform bounded HTTPS reachability evidence for one Mail.ru public URL."""
    try:
        result = probe_public_url(public_url, opener=opener)
        return ProbeOutcome(
            ok=True, checks={"url_allowed": True, "http_accessible": True}, result=result
        )
    except ProbeFailure as failure:
        return ProbeOutcome(
            ok=False,
            checks={"url_allowed": True},
            error=failure.to_payload(),
        )
    except ValueError:
        return ProbeOutcome(
            ok=False,
            error={
                "kind": "invalid_public_url",
                "message": "URL did not match the Mail.ru allowlist",
            },
        )


def probe_public_url(public_url: str, *, opener: HttpOpener | None = None) -> dict[str, Any]:
    """Use only bounded HTTPS requests and report a fingerprint, never the URL itself."""
    _validate_public_url(public_url)
    active_opener = cast(HttpOpener, opener or build_opener(_NoRedirectHandler()))
    head = _bounded_http_request(active_opener, public_url, method="HEAD", read_body=False)
    get = _bounded_http_request(active_opener, public_url, method="GET", read_body=True)
    if not 200 <= get["status_code"] < 400:
        raise ProbeFailure(
            "public_url_unavailable",
            "public URL did not return a successful HTTP status",
            {"status_code": get["status_code"]},
        )
    content_type = get["content_type"]
    return {
        "public_url_fingerprint": _public_url_fingerprint(public_url),
        "http_accessible": True,
        "head_status_code": head["status_code"],
        "status_code": get["status_code"],
        "content_type": content_type,
        "redirect_count": head["redirect_count"] + get["redirect_count"],
        "download_mode": "browser_page" if "html" in content_type.lower() else "unknown",
    }


def main(
    probe_name: str,
    argv: Sequence[str] | None = None,
    *,
    runner: CommandRunner | None = None,
    opener: HttpOpener | None = None,
    environment: Mapping[str, str] | None = None,
    private_input: TextIO | None = None,
) -> int:
    """Execute an entrypoint and emit exactly one sanitized JSON object."""
    started_at = _timestamp()
    env = os.environ if environment is None else environment
    active_runner = runner or SubprocessRcloneRunner()
    input_stream = sys.stdin if private_input is None else private_input
    artifact_dir: str | None = None
    try:
        args = _parser_for(probe_name).parse_args(argv)
        if args.help:
            outcome = ProbeOutcome(
                ok=True,
                result={
                    "help": {
                        "json_only": True,
                        "input": "stdin" if probe_name == "04_public_url_probe" else "arguments",
                    }
                },
            )
        else:
            artifact_dir = args.artifacts_dir or env.get("HMC_ARTIFACTS_DIR")
            outcome = _run_named_probe(
                probe_name, args, active_runner, opener, env, private_input=input_stream
            )
    except ValueError:
        outcome = _invalid_input_outcome()
    except Exception:
        outcome = ProbeOutcome(
            ok=False,
            error={
                "kind": "unexpected_probe_error",
                "message": "probe failed without a safe diagnostic",
            },
        )

    payload = {
        "probe": probe_name,
        "started_at": started_at,
        "finished_at": _timestamp(),
        **outcome.to_payload(),
    }
    artifact_requested = artifact_dir is not None
    payload["artifact"] = {"requested": artifact_requested, "written": False}
    if artifact_requested:
        try:
            payload["artifact"]["written"] = True
            _write_artifact(
                payload,
                probe_name=probe_name,
                artifact_dir=artifact_dir,
            )
        except OSError:
            payload["ok"] = False
            payload["artifact"]["written"] = False
            payload["error"] = {
                "kind": "artifact_write_failed",
                "message": "could not write the sanitized local probe artifact",
            }
    print(json.dumps(sanitize_value(payload), ensure_ascii=False, sort_keys=True))
    return 0 if payload["ok"] else 1


def _run_named_probe(
    probe_name: str,
    args: argparse.Namespace,
    runner: CommandRunner,
    opener: HttpOpener | None,
    environment: Mapping[str, str],
    *,
    private_input: TextIO,
) -> ProbeOutcome:
    if probe_name == "00_env_probe":
        return run_env_probe(remote=_remote_from_args(args, environment), runner=runner)
    if probe_name == "01_file_ops_probe":
        return run_file_ops_probe(
            remote=_remote_from_args(args, environment),
            root=_root_from_args(args, environment),
            runner=runner,
            live_enabled=environment.get("HMC_LIVE") == "1",
        )
    if probe_name == "02_publish_probe":
        return run_publish_probe(
            remote=_remote_from_args(args, environment),
            root=_root_from_args(args, environment),
            runner=runner,
            live_enabled=environment.get("HMC_LIVE") == "1",
            opener=opener,
        )
    if probe_name == "03_unlink_probe":
        return run_unlink_probe(
            remote=_remote_from_args(args, environment),
            root=_root_from_args(args, environment),
            runner=runner,
            live_enabled=environment.get("HMC_LIVE") == "1",
            opener=opener,
        )
    if probe_name == "04_public_url_probe":
        return run_public_url_probe(
            public_url=_public_url_from_private_input(private_input), opener=opener
        )
    raise ValueError("unknown probe")


def _parser_for(probe_name: str) -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(prog=probe_name, add_help=False)
    parser.add_argument("--help", action="store_true")
    parser.add_argument("--json", action="store_true", help="emit JSON (the only output mode)")
    parser.add_argument(
        "--artifacts-dir", help="optional local directory for a sanitized JSON report"
    )
    if probe_name in {"00_env_probe", "01_file_ops_probe", "02_publish_probe", "03_unlink_probe"}:
        parser.add_argument("--remote", help="simple rclone remote name, for example mailru:")
        if probe_name != "00_env_probe":
            parser.add_argument("--root", help="unique /TEST/hermes-mailcloud-* root")
    elif probe_name != "04_public_url_probe":
        raise ValueError("unknown probe")
    return parser


def _public_url_from_private_input(private_input: TextIO) -> str:
    value = private_input.readline(MAX_PRIVATE_INPUT_BYTES + 1)
    if not value or len(value) > MAX_PRIVATE_INPUT_BYTES or private_input.read(1):
        raise ValueError("public capability input must contain one bounded line")
    public_url = value.strip()
    if not public_url:
        raise ValueError("public capability input was empty")
    return public_url


def _remote_from_args(args: argparse.Namespace, environment: Mapping[str, str]) -> str:
    return validate_remote(args.remote or environment.get("HMC_REMOTE", "mailru:"))


def _root_from_args(args: argparse.Namespace, environment: Mapping[str, str]) -> str:
    return resolve_test_root(args.root or environment.get("HMC_TEST_ROOT"))


def _require_success(runner: CommandRunner, check: str, args: list[str]) -> CommandResult:
    result = _runner_result(runner, args)
    if result.returncode != 0:
        raise ProbeFailure(
            "rclone_command_failed",
            f"{check} command failed",
            {
                "command": args[0],
                "exit_code": result.returncode,
                "stderr_tail": _safe_tail(result.stderr),
            },
        )
    return result


def _runner_result(runner: CommandRunner, args: list[str]) -> CommandResult:
    try:
        return runner.run(args, timeout=RCLONE_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return CommandResult(returncode=1, stdout="", stderr="rclone process could not be started")


def _indicates_missing_path(stderr: str) -> bool:
    return bool(re.search(r"(?i)(not found|does not exist|directory.*not)", stderr))


def _safe_tail(value: str) -> str:
    return redact_text(value[-512:])


def _is_descendant(path: str, root: str) -> bool:
    return path.startswith(f"{root}/")


def _live_not_enabled_outcome() -> ProbeOutcome:
    return ProbeOutcome(
        ok=False,
        error={
            "kind": "live_not_enabled",
            "message": "set HMC_LIVE=1 before a mutating probe can run",
        },
    )


def _prove_root_is_absent(runner: CommandRunner, root_target: str) -> None:
    preflight = _runner_result(runner, ["lsd", root_target])
    if preflight.returncode == 0:
        raise ProbeFailure("test_root_exists", "generated test root already exists")
    if not _indicates_missing_path(preflight.stderr):
        raise ProbeFailure(
            "test_root_absence_unproven",
            "could not prove that the generated test root is absent",
            {"exit_code": preflight.returncode, "stderr_tail": _safe_tail(preflight.stderr)},
        )


def _extract_public_url(stdout: str) -> str:
    match = PUBLIC_URL_PATTERN.search(stdout)
    if match is None:
        raise ProbeFailure("public_link_failed", "rclone link did not return an allowed public URL")
    public_url = match.group(0)
    try:
        _validate_public_url(public_url)
    except ValueError as error:
        raise ProbeFailure(
            "public_link_failed", "rclone link did not return an allowed public URL"
        ) from error
    return public_url


def _outcome_with_cleanup(
    checks: dict[str, bool],
    result: dict[str, Any],
    manifest: CleanupManifest | None,
    failure: ProbeFailure | None,
) -> ProbeOutcome:
    cleanup = manifest.to_payload() if manifest is not None else None
    if failure is None and cleanup is not None and not cleanup["complete"]:
        failure = ProbeFailure("cleanup_failed", "same-run cleanup did not complete", cleanup)
    return ProbeOutcome(
        ok=failure is None,
        checks=checks,
        result=result,
        cleanup=cleanup,
        error=failure.to_payload() if failure is not None else None,
    )


def _invalid_input_outcome() -> ProbeOutcome:
    return ProbeOutcome(
        ok=False,
        error={"kind": "invalid_input", "message": "probe input did not pass the safety policy"},
    )


def _validate_public_url(public_url: str) -> None:
    parsed = urlsplit(public_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != PUBLIC_HOST
        or parsed.port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path.startswith("/public/")
    ):
        raise ValueError("URL is not an allowed Mail.ru public URL")


def _bounded_http_request(
    opener: HttpOpener, public_url: str, *, method: str, read_body: bool
) -> dict[str, Any]:
    current_url = public_url
    redirects = 0
    while True:
        request = Request(
            current_url, method=method, headers={"User-Agent": "hermes-mailcloud-probe/0.1"}
        )
        try:
            response = opener.open(request, timeout=RCLONE_TIMEOUT_SECONDS)
            status = getattr(response, "status", None)
            status_code = int(status if status is not None else response.getcode())
            headers = response.headers
        except HTTPError as error:
            response = error
            status_code = error.code
            headers = error.headers
        except URLError as error:
            raise ProbeFailure(
                "public_url_request_failed", "bounded HTTP request failed"
            ) from error

        location = headers.get("Location") if headers else None
        if 300 <= status_code < 400 and location:
            if redirects >= MAX_HTTP_REDIRECTS:
                raise ProbeFailure(
                    "redirect_limit_exceeded", "public URL exceeded the redirect limit"
                )
            candidate = urljoin(current_url, location)
            try:
                _validate_public_url(candidate)
            except ValueError as error:
                raise ProbeFailure(
                    "redirect_not_allowed", "public URL redirected outside the allowlist"
                ) from error
            current_url = candidate
            redirects += 1
            continue

        try:
            if read_body:
                response.read(MAX_HTTP_BODY_BYTES)
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        content_type = headers.get("Content-Type", "") if headers else ""
        return {
            "status_code": status_code,
            "content_type": content_type.split(";", maxsplit=1)[0],
            "redirect_count": redirects,
        }


def _public_url_fingerprint(public_url: str) -> str:
    return f"sha256:{hashlib.sha256(public_url.encode('utf-8')).hexdigest()}"


def _write_artifact(payload: dict[str, Any], *, probe_name: str, artifact_dir: str) -> None:
    destination = Path(artifact_dir)
    destination.mkdir(parents=True, exist_ok=True)
    safe_payload = sanitize_value(payload)
    filename = (
        f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{probe_name}-{secrets.token_hex(4)}.json"
    )
    temporary = destination / f".{filename}.tmp"
    final = destination / filename
    temporary.write_text(
        json.dumps(safe_payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(final)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        del message
        raise ValueError("invalid arguments")

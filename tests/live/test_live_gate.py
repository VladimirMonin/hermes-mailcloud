"""Live test gate; actual provider scenarios are added with later command slices."""

from __future__ import annotations

import os

import pytest

from hermes_mailcloud.probes.core import validate_test_root

pytestmark = pytest.mark.live


def _configured_live_root() -> str:
    """Skip rather than touching a provider unless the owner explicitly enabled it."""
    if os.environ.get("HMC_LIVE") != "1":
        pytest.skip("set HMC_LIVE=1 to run live Mail.ru tests")
    root = os.environ.get("HMC_TEST_ROOT")
    if not root:
        pytest.skip("set HMC_TEST_ROOT to a unique /TEST/hermes-mailcloud-* root")
    return validate_test_root(root)


@pytest.fixture
def isolated_live_root() -> str:
    return _configured_live_root()


def test_live_suite_requires_explicit_opt_in(isolated_live_root: str) -> None:
    """Keep the gate executable without performing any remote operation in Stage 3."""
    assert isolated_live_root == validate_test_root(isolated_live_root)


def test_live_gate_accepts_a_canonical_isolated_root(monkeypatch: pytest.MonkeyPatch) -> None:
    root = "/TEST/hermes-mailcloud-20260724T235959Z-abc12345"
    monkeypatch.setenv("HMC_LIVE", "1")
    monkeypatch.setenv("HMC_TEST_ROOT", root)

    assert _configured_live_root() == root


@pytest.mark.parametrize(
    "root",
    [
        "/TEST/hermes-mailcloud-20260724T235959Z-abc12345/child",
        "/TEST/hermes-mailcloud-20260724T235959Z-abc12345/../outside",
        "/TEST/hermes-mailcloud-20260724T235959Z-abc12345-suffix",
    ],
)
def test_live_gate_rejects_noncanonical_or_colliding_roots(
    monkeypatch: pytest.MonkeyPatch, root: str
) -> None:
    monkeypatch.setenv("HMC_LIVE", "1")
    monkeypatch.setenv("HMC_TEST_ROOT", root)

    with pytest.raises(ValueError):
        _configured_live_root()

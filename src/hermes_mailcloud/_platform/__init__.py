"""Select the OS-specific private storage backend for the link journal."""

from __future__ import annotations

import os
from types import ModuleType


class PrivateStorageError(Exception):
    """Safe private-storage failure that never carries a path, URL or OS exception text."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _load_backend() -> ModuleType | None:
    if os.name == "nt":
        try:
            from . import journal_windows as backend
        except ImportError:
            return None
        return backend
    from . import journal_posix as backend

    return backend


_BACKEND = _load_backend()


def backend() -> ModuleType:
    """Return the platform backend or fail closed before any public operation side effect."""
    if _BACKEND is None:
        raise PrivateStorageError("secure local link journal storage is unavailable")
    return _BACKEND


__all__ = ["PrivateStorageError", "backend"]

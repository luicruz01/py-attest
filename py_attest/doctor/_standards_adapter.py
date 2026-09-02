"""Thin adapter over py_attest.standards.registry (F0.4), not yet on main.

standards_valid and standards_in_sync program against this module instead of importing
py_attest.standards.registry directly, so the day F0.4 lands, only this file's ImportError
guard needs to go away -- the two checks keep working unmodified.
"""

from __future__ import annotations

try:
    from py_attest.standards import registry as _registry  # type: ignore[import-not-found]
except ImportError:
    _registry = None

F0_4_PENDING_MESSAGE = "waiting for F0.4 (py_attest.standards not available)"


def is_available() -> bool:
    return _registry is not None

"""Egress: turn a diff (+ context) into the payload sent to the provider (ADR-004 SS3).

Both modes share one shape: :class:`EgressResult` carries the assembled
``user_content`` (the provider's ``ProviderRequest.user_content``) and the
``report_block`` published as the report's ``egress`` field (TRD SS4.3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EgressResult:
    mode: str
    user_content: str
    report_block: dict[str, Any]
    # alias -> real path (minimized mode only; empty for raw). A finding's `path` in
    # the provider's response can only be an alias the model was shown, never the real
    # path -- reviewer.py uses this to translate a finding's path back before checking
    # it against the real diff (validation.py's changed_line_index is keyed by real
    # paths, since it's built from the real diff, not the minimized payload).
    path_aliases: dict[str, str] = field(default_factory=dict)

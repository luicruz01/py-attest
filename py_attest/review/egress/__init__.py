"""Egress: turn a diff (+ context) into the payload sent to the provider (ADR-004 SS3).

Both modes share one shape: :class:`EgressResult` carries the assembled
``user_content`` (the provider's ``ProviderRequest.user_content``) and the
``report_block`` published as the report's ``egress`` field (TRD SS4.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EgressResult:
    mode: str
    user_content: str
    report_block: dict[str, Any]

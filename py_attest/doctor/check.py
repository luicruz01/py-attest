"""Base types for doctor checks: the Check contract, its result, and run context."""

from __future__ import annotations

import abc
import enum
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from py_attest.config import Config

Severity = Literal["S1", "S2", "S3"]


class CheckStatus(enum.Enum):
    PASS = "pass"  # noqa: S105 - status label, not a credential
    FAIL = "fail"
    SKIP = "skip"
    ERROR = "error"


@dataclass(frozen=True)
class CheckResult:
    status: CheckStatus
    message: str
    remedy: str | None = None
    rule_id: str | None = None


@dataclass(frozen=True)
class DoctorContext:
    repo_root: Path
    offline: bool
    config: Config


class Check(abc.ABC):
    """A single doctor diagnostic: a stable id, a fixed severity, and a run method."""

    id: str
    severity: Severity

    @abc.abstractmethod
    def run(self, ctx: DoctorContext) -> CheckResult:
        """Run this check against ``ctx.repo_root`` and return its result."""

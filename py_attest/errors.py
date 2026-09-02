class AttestError(Exception):
    """Base class for attest errors that map to a specific exit code."""


class BlockedError(AttestError):
    """Gate verdict is BLOCK (exit 2)."""


class IncompatibleError(AttestError):
    """Engine/template incompatibility, ADR-003 (exit 3)."""


class InconclusiveError(AttestError):
    """Execution failure or incomplete review; never approves (exit 4)."""

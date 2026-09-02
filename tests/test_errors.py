from py_attest.errors import (
    AttestError,
    BlockedError,
    IncompatibleError,
    InconclusiveError,
)


def test_blocked_error_is_an_attest_error() -> None:
    assert issubclass(BlockedError, AttestError)


def test_incompatible_error_is_an_attest_error() -> None:
    assert issubclass(IncompatibleError, AttestError)


def test_inconclusive_error_is_an_attest_error() -> None:
    assert issubclass(InconclusiveError, AttestError)

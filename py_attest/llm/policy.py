"""Retry/attempt policy for provider calls (ADR-002 "Politica de reintentos y timeouts").

Lives in the engine, not in providers: a provider makes exactly one call attempt per
invocation (SDKs are constructed with their own internal retries disabled -- ADR-002 --
so this loop owns the retry count that gets stamped on the artifact as ``attempts``).
Per-call timeout is a provider-construction concern (the provider's SDK client is built
with ``config.limits.provider_timeout``), not this loop's.
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable

from py_attest.llm.types import Provider, ProviderFailure, ProviderRequest, ProviderResponse

# ADR-002: ProviderTransient retries up to 2 additional times, backoff 2s then 6s.
BACKOFF_SECONDS: tuple[float, ...] = (2.0, 6.0)

# ADR-002: StructuredOutputInvalid retries exactly once, no specified backoff.
_MAX_ATTEMPTS_BY_CATEGORY = {
    "transient": len(BACKOFF_SECONDS) + 1,
    "invalid_structured_output": 2,
}


def run_with_policy(
    provider: Provider,
    request: ProviderRequest,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> ProviderResponse:
    """Call ``provider`` under the ADR-002 retry policy.

    Returns the response with ``attempts`` stamped.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            response = provider.complete_structured(request)
        except ProviderFailure as exc:
            max_attempts = _MAX_ATTEMPTS_BY_CATEGORY.get(exc.category, 1)
            if attempt >= max_attempts:
                raise
            sleep(BACKOFF_SECONDS[attempt - 1] if exc.category == "transient" else 0.0)
            continue
        return dataclasses.replace(response, attempts=attempt)

"""Per-model parameter capabilities, learned at runtime.

The gateway fronts many upstream providers and they do not accept the same
request parameters. Two constraints confirmed against the live endpoint:

* `ling-3.0-flash-free` rejects `response_format` ("does not support feature:
  structured-outputs").
* `kimi-k3` rejects any temperature other than 1.

Hardcoding a table would rot as the roster changes, so instead the client
inspects the 400 it gets back, disables the offending parameter for that model
and retries. The result is cached per process, so the cost is one wasted call
per model per worker lifetime.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, replace

# Matched against the gateway's error text, which passes the upstream message
# through verbatim.
_RESPONSE_FORMAT_MARKERS = (
    "structured-outputs",
    "structured outputs",
    "response_format",
    "json_object",
    "json mode",
)
_TEMPERATURE_MARKER = re.compile(r"temperature", re.IGNORECASE)
_MAX_TOKENS_MARKERS = ("max_tokens", "max_completion_tokens")


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    supports_response_format: bool = True
    supports_temperature: bool = True
    # Some models only accept one fixed temperature value.
    forced_temperature: float | None = None
    uses_max_completion_tokens: bool = False


_lock = threading.Lock()
_cache: dict[str, ModelCapabilities] = {}


def get(model: str) -> ModelCapabilities:
    with _lock:
        return _cache.setdefault(model, ModelCapabilities())


def reset() -> None:
    with _lock:
        _cache.clear()


def learn_from_error(model: str, message: str) -> bool:
    """Narrows a model's capabilities based on a rejection.

    Returns True when something new was learned, meaning the caller should
    retry. False means the failure was not a parameter-compatibility problem.
    """
    lowered = message.lower()
    current = get(model)
    updated = current

    if any(marker in lowered for marker in _RESPONSE_FORMAT_MARKERS):
        updated = replace(updated, supports_response_format=False)
    elif _TEMPERATURE_MARKER.search(lowered):
        forced = _forced_temperature(message)
        updated = replace(updated, supports_temperature=False, forced_temperature=forced)
    elif any(marker in lowered for marker in _MAX_TOKENS_MARKERS):
        updated = replace(updated, uses_max_completion_tokens=True)

    if updated == current:
        return False
    with _lock:
        _cache[model] = updated
    return True


def _forced_temperature(message: str) -> float | None:
    """Extracts the single permitted value from e.g. "only 1 is allowed"."""
    match = re.search(r"only\s+([0-9]*\.?[0-9]+)\s+is allowed", message, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def snapshot() -> dict[str, ModelCapabilities]:
    """Current knowledge, surfaced in the ops console agent panel."""
    with _lock:
        return dict(_cache)

"""Integer media time. `TICKS_PER_SECOND = 120000`."""

from __future__ import annotations

TICKS_PER_SECOND = 120_000
JS_MAX_SAFE_INTEGER = 2**53 - 1
MAX_COMMANDS_PER_BATCH = 100
MAX_ELEMENTS_PER_DOCUMENT = 5_000
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024
MAX_TRACKS_PER_KIND = 16
LEASE_TTL_SECONDS = 5 * 60
LEASE_HEARTBEAT_SECONDS = 30


def assert_safe_ticks(ticks: int, *, label: str) -> int:
    if not isinstance(ticks, int) or isinstance(ticks, bool):
        raise ValueError(f"{label} 必须是整数 tick。")
    if ticks < 0 or ticks > JS_MAX_SAFE_INTEGER:
        raise ValueError(f"{label} 超出安全整数 tick 范围。")
    return ticks


def ticks_from_ms(duration_ms: int | None) -> int:
    if duration_ms is None or duration_ms <= 0:
        return TICKS_PER_SECOND
    return int(duration_ms) * TICKS_PER_SECOND // 1000

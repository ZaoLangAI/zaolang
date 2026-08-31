"""Bucket CORS helpers shared by MinIO and Tencent COS.

Laptop and production can share one object-store bucket. Each environment's
`ensure_bucket` must *union* its `cors_origins` into the existing rule rather
than replacing the whole list — otherwise a local `make seed` wipes the
production origin and browser PUTs on the public host start failing CORS.
"""

from __future__ import annotations

from typing import Any


def merge_cors_origins(*groups: list[str] | tuple[str, ...]) -> list[str]:
    """Stable, de-duplicated union. Earlier groups keep their relative order."""
    merged: list[str] = []
    for group in groups:
        for origin in group:
            cleaned = origin.strip()
            if cleaned and cleaned not in merged:
                merged.append(cleaned)
    return merged


def origins_from_cors_config(config: object) -> list[str]:
    """Reads AllowedOrigin(s) out of either COS or AWS/MinIO CORS JSON."""
    if not isinstance(config, dict):
        return []
    rules: Any = config.get("CORSRule") or config.get("CORSRules") or []
    if isinstance(rules, dict):
        rules = [rules]
    origins: list[str] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        raw: Any = rule.get("AllowedOrigin") or rule.get("AllowedOrigins") or []
        if isinstance(raw, str):
            raw = [raw]
        origins.extend(item for item in raw if isinstance(item, str))
    return origins

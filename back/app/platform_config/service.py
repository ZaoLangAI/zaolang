"""Runtime configuration centre.

Reads go through a short-lived Redis cache so hot paths (quoting, routing) do
not hit Postgres per request. Writes append a new version, flip the active flag
inside one transaction, and bust the cache, so a change takes effect everywhere
without a restart and can be rolled back to any earlier version.
"""

from __future__ import annotations

import contextlib
import json
import logging
from typing import Any, TypeVar

import redis
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.rate_limit import get_redis
from app.domain.errors import NotFound, ValidationFailed
from app.models import PlatformConfig
from app.models.base import utcnow
from app.platform_config.schemas import CONFIG_SCHEMAS, DEFAULT_CONFIGS, ConfigSection

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 30
CACHE_PREFIX = "cfg:v1:"

T = TypeVar("T", bound=ConfigSection)


def _cache_key(key: str) -> str:
    return f"{CACHE_PREFIX}{key}"


def validate(key: str, value: dict[str, Any]) -> ConfigSection:
    """Parses a payload against its schema.

    Raising `ValidationFailed` here is what guarantees no invalid config can
    ever reach the database.
    """
    schema = CONFIG_SCHEMAS.get(key)
    if schema is None:
        raise ValidationFailed(f"未知的配置键: {key}", key=key)
    try:
        return schema.model_validate(value)
    except Exception as exc:
        raise ValidationFailed(f"配置校验失败: {exc}", key=key) from exc


def get_raw(session: Session, key: str) -> dict[str, Any]:
    """Active value for a key, falling back to the built-in default."""
    cache = _try_cache_get(key)
    if cache is not None:
        return cache

    row = session.scalar(
        select(PlatformConfig).where(PlatformConfig.key == key, PlatformConfig.is_active.is_(True))
    )
    value = dict(row.value_json) if row is not None else dict(DEFAULT_CONFIGS.get(key, {}))
    _try_cache_set(key, value)
    return value


def get_typed[T: ConfigSection](session: Session, key: str, schema: type[T]) -> T:
    """Typed accessor.

    A stored value that no longer parses (because the schema tightened) falls
    back to the default rather than taking the service down.
    """
    raw = get_raw(session, key)
    try:
        return schema.model_validate(raw)
    except Exception:
        logger.warning("config %s failed validation; using defaults", key, exc_info=True)
        return schema.model_validate(DEFAULT_CONFIGS[key])


def set_value(
    session: Session,
    key: str,
    value: dict[str, Any],
    *,
    actor_user_id: str | None,
    note: str | None = None,
) -> PlatformConfig:
    """Writes a new active version. The previous version stays for rollback."""
    validated = validate(key, value)
    normalised = validated.model_dump(mode="json")

    latest = session.scalar(
        select(PlatformConfig.version)
        .where(PlatformConfig.key == key)
        .order_by(PlatformConfig.version.desc())
        .limit(1)
    )
    next_version = (latest or 0) + 1

    session.execute(
        update(PlatformConfig)
        .where(PlatformConfig.key == key, PlatformConfig.is_active.is_(True))
        .values(is_active=False)
    )
    row = PlatformConfig(
        key=key,
        version=next_version,
        value_json=normalised,
        is_active=True,
        note=note,
        created_by_user_id=actor_user_id,
        created_at=utcnow(),
    )
    session.add(row)
    session.flush()
    invalidate(key)
    return row


def rollback(
    session: Session, key: str, target_version: int, *, actor_user_id: str | None
) -> PlatformConfig:
    """Re-applies an earlier version as a new version.

    History is never rewritten: rolling back moves forward to a copy of the old
    value, so the audit trail shows both the mistake and the correction.
    """
    target = session.scalar(
        select(PlatformConfig).where(
            PlatformConfig.key == key, PlatformConfig.version == target_version
        )
    )
    if target is None:
        raise NotFound(f"配置 {key} 不存在版本 {target_version}。")
    return set_value(
        session,
        key,
        dict(target.value_json),
        actor_user_id=actor_user_id,
        note=f"回滚到版本 {target_version}",
    )


def history(session: Session, key: str, limit: int = 20) -> list[PlatformConfig]:
    return list(
        session.scalars(
            select(PlatformConfig)
            .where(PlatformConfig.key == key)
            .order_by(PlatformConfig.version.desc())
            .limit(limit)
        )
    )


def all_keys() -> list[str]:
    return sorted(CONFIG_SCHEMAS)


def invalidate(key: str) -> None:
    try:
        get_redis().delete(_cache_key(key))
    except redis.RedisError:
        # The TTL bounds the staleness window even if the bust fails.
        logger.warning("failed to invalidate config cache for %s", key)


def _try_cache_get(key: str) -> dict[str, Any] | None:
    try:
        cached = get_redis().get(_cache_key(key))
    except redis.RedisError:
        return None
    if not cached:
        return None
    try:
        parsed = json.loads(cached)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _try_cache_set(key: str, value: dict[str, Any]) -> None:
    with contextlib.suppress(redis.RedisError):
        get_redis().setex(_cache_key(key), CACHE_TTL_SECONDS, json.dumps(value, ensure_ascii=False))


def is_enabled(session: Session, flag: str, *, user_id: str | None = None) -> bool:
    """Evaluates a feature flag, including percentage rollout.

    Bucketing is a stable hash of the user id, so a user's experience does not
    flip between requests.
    """
    from app.platform_config.schemas import FeatureFlags

    flags = get_typed(session, "feature_flags", FeatureFlags)
    if not getattr(flags, flag, False):
        return False

    percentage = flags.rollout_percentages.get(flag)
    if percentage is None or percentage >= 100:
        return True
    if user_id is None:
        return False
    bucket = int.from_bytes(user_id.encode()[-4:], "big") % 100
    return bucket < percentage

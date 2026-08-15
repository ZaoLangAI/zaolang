---
name: zaolang-platform-config
description: Runtime configuration — strongly-typed, versioned, audited, and rollback-capable schemas for pricing / royalty / feature_flags / shortform / llm_providers plus the three moderation-config categories (content, learning, skill). Use when adding or relocating runtime settings, changing pricing or flags, or debugging why a config change did not take effect.
disable-model-invocation: true
---

# Runtime Config Center & Feature Flags

## Scope

Runtime config is surfaced by business ownership: the config center's home page shows global feature flags and short-video specs directly; pricing/royalty and the three moderation-rule categories only open via the "configure" button next to each business page's refresh control. Model endpoints are still versioned inside `llm_providers`, but reachable only through a dedicated masked API. Agent provider/model bindings live on `AgentProfile` and are not part of `PlatformConfig`. Per-endpoint timeout and concurrency are maintained on the model page — there's no separate global LLM-reliability section.

## Key Paths

| File | Contents |
| --- | --- |
| `back/app/platform_config/schemas.py` | `CONFIG_SCHEMAS` (key → pydantic type) and `DEFAULT_CONFIGS` (defaults) |
| `back/app/platform_config/service.py` | `get_typed` / `get_raw` / `set_value` / `rollback` / `history` / `invalidate` / `is_enabled` |
| `back/app/api/v1/admin/config.py` | reads require `viewer`; writes and rollback require **admin** |
| `front/src/components/admin/config/runtime-config-panel.tsx` | the reusable form/JSON editor, diff view, reason field, history, and rollback UI |
| `front/src/components/admin/models/llm-providers-panel.tsx` | model management: a flat primary/backup list plus per-endpoint primary/backup, with full CRUD |

Nine keys: `pricing`, `royalty`, `marketplace`, `feature_flags`, `shortform`, `llm_providers`, `content_moderation`, `learning_moderation`, `skill_moderation`. `marketplace` governs unlock commission and price caps; `feature_flags.marketplace_enabled` is its master switch. The retired `providers`, `agents`, `moderation`, and `llm_reliability` keys are kept only as inert history — they can no longer be read or rolled back to.

Inside `llm_providers`, every endpoint declares exactly one `kind`: `general` (text and image understanding) or `media` (image/video/audio generation). Judgment-role and assist-role `AgentProfile`s manually pick a default provider endpoint, a compatible model, and an optional backup endpoint; a non-default agent without an explicit binding inherits its role's default agent. A `media` endpoint declares a single model id (`model`) plus input/output modalities and **`protocol`** (an HTTP-contract standard name, not a gateway provider name); its capability tags are derived by `capabilities_for_modalities`, and it enters `router.py`'s dynamic candidate catalogue for `intent_router`'s LLM-driven selection. Media endpoints have no primary/backup ordering or concurrency scheduling semantics. `protocol` lives in this JSON blob — it never touches SQLAlchemy or Alembic.

## Invariants

1. **Reads only go through `get_typed(session, key, Schema)`**, returning a strongly-typed object. Never subscript `get_raw`'s result directly — schema validation is the only barrier stopping one bad edit from taking production down.
2. **Writes are versioned appends**: `set_value` inserts a new `PlatformConfig` version, invalidates the Redis cache, and writes to `AuditLog` (actor, before/after summary, reason). Updating the table directly, bypassing the service, means losing history, losing the audit trail, and a stale cache.
3. **Every config change requires a reason**, and so does `rollback`. High-risk admin operations require a second confirmation (see `zaolang-admin-console`).
4. **Secret fields never enter the general config API**: `llm_providers`'s list/get/update/diff/history/rollback all reject it — only the dedicated model API returns masked values and connectivity status.
5. **Cache invalidation never relies on TTL alone**: both `set_value` and `rollback` call `invalidate(key)`. If Redis is unavailable, the service falls back to reading the database directly (the probe runs inside `begin_nested`, so it never poisons the transaction).
6. **Defaults must let an empty database work.** `DEFAULT_CONFIGS` is what `get_typed` falls back to when the key doesn't exist in the database yet — tests and fresh deployments both depend on it.
7. **Never bring back a routing-score-weight config section.** Which provider wins is decided by `intent_router`'s LLM judgment (`zaolang-agent-gateway` invariant #1), not a tunable number — this module only owns the provider catalogue's hard switches: existence, enablement, and quota limits.
8. **A `get_typed` validation failure falls back to the whole `DEFAULT_CONFIGS["llm_providers"]` (empty `endpoints`)** — one bad endpoint can wipe the entire routing catalogue. So `LlmProviderEndpoint.protocol` must be optional (`None`-able): when the field is missing, `_migrate_legacy_fields` infers it from capabilities (video-only → `minimax`, else → `openai`). `kind=general` always clears `protocol`. An explicit admin upsert is validated strictly: an unimplemented protocol, `openai`+video, or `minimax`+image/audio all raise `ValidationFailed` (HTTP 422) — silent fallback is never allowed. Existing endpoints with a cross-protocol mismatch are individually skipped (with a warning logged) inside `LlmProviderConfig`, rather than failing the whole config.

## Extension Points

**Add a config field**

1. Add the field to the relevant `ConfigSection` in `schemas.py` (**with a default**, or deserializing an existing version breaks).
2. Add the matching field to `DEFAULT_CONFIGS`.
3. Update call sites to read the new field directly — never leave a type-bypassing `getattr(cfg, "x", fallback)`.
4. The frontend's `config-console.tsx` auto-supports it via the JSON editor; sections with a dedicated panel (pricing, flags, short-video) need explicit updates too — `runtime-config-panel.tsx`'s `ShortformForm` is a hand-written field list, not schema-auto-rendered, so a new field needs an explicit control (e.g. `ShortformConfig.enable_clarifying_questions` / `enable_preview_picker` / `preview_candidate_count`, the short-video studio's follow-up-question and preview-picker toggles).
5. Add a unit test to `back/tests/unit/test_platform_config.py`.

**Add a new config section**: add an entry to both `CONFIG_SCHEMAS` and `DEFAULT_CONFIGS` — `all_keys()` picks it up automatically, and it appears in the admin list on its own.

**Add a feature flag**: add a boolean field to `FeatureFlags` → check it at call sites with `is_enabled(session, "flag_name", user_id=...)`. Gradual rollout is hashed by user_id — don't implement your own bucketing. The drama editor's five flags (`drama_studio_enabled` / `web_editor_enabled` / `variant_export_enabled` / `editor_ai_enabled` / `editor_mcp_enabled`) default to false; the last three depend on `web_editor_enabled`. Local `make seed` turns them on — never write that seed behavior into `DEFAULT_CONFIGS`. See `zaolang-editor-drama`.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/unit/test_platform_config.py tests/integration/test_admin_ops_platform.py -v
```

After changing something, exercise it in admin at `/admin/config`: edit → view the diff → roll back → confirm both actions appear with their reasons in `/admin/audit` (Log Center).

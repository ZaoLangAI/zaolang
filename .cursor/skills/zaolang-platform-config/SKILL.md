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
| `front/src/components/admin/models/llm-providers-panel.tsx` | model management: a flat primary/backup list plus per-endpoint primary/backup, with full CRUD. Vendor list prices can be typed in USD or CNY; CNY uses a form-local rate (default 7.2, never persisted) and integer micro-unit math, and the upsert still writes `*_micro_usd` only |
| `back/app/providers/model_catalog.py` | `ModelCatalogEntry.price_items`: each known model's real billable line items, one per `(vendor, model)` record, sourced from that vendor's own actual resale channel and never shared between AiHubMix and DMXAPI for the same nominal upstream model (see invariant #9) |
| `back/app/domain/costs/service.py` | turns a `LlmProviderEndpoint`'s typed pricing sections into what one call cost, in micro-USD; dispatches by `billing_profile` for a shape that isn't the default per-second/per-image/per-token one (Doubao Seedance's token formula) |

Nine keys: `pricing`, `royalty`, `marketplace`, `feature_flags`, `shortform`, `llm_providers`, `content_moderation`, `learning_moderation`, `skill_moderation`. `marketplace` governs unlock commission and price caps; `feature_flags.marketplace_enabled` is its master switch. The retired `providers`, `agents`, `moderation`, and `llm_reliability` keys are kept only as inert history — they can no longer be read or rolled back to.

Inside `llm_providers`, every endpoint declares exactly one `kind`: `general` (text and image understanding) or `media` (image/video/audio generation). Judgment-role and assist-role `AgentProfile`s manually pick a default provider endpoint, a compatible model, and an optional backup endpoint; a non-default agent without an explicit binding inherits its role's default agent. A `media` endpoint declares a single model id (`model`) plus input/output modalities and **`protocol`** (an HTTP-contract standard name, not a gateway provider name); its capability tags are derived by `capabilities_for_modalities`, and it enters `router.py`'s dynamic candidate catalogue for `intent_router`'s LLM-driven selection. Media endpoints have no primary/backup ordering or concurrency scheduling semantics. `protocol` lives in this JSON blob — it never touches SQLAlchemy or Alembic. An invalid CNY rate or price on the admin form is rejected — never coerced to zero or to the default 7.2.

`billing_profile` (a free-form string on `LlmProviderEndpoint`, copied from the picked catalog entry) is metadata for which cost-calculation shape applies — `app.domain.costs.service.SEEDANCE_TOKENS_BILLING_PROFILE` (`"seedance_tokens"`) is the one value the cost code actually branches on today, to bill `MediaPricing.token_video`'s per-million-token formula instead of `MediaPricing.video`'s per-second rate for the same `text_to_video`/`image_to_video`/`video_to_video` capabilities. Every other pricing-shape difference (Doubao Seedream's size-tiered image price, a free reference-image count, a text model's cached-input rate) is handled generically inside the per-section cost functions regardless of `billing_profile`.

## Invariants

1. **Reads only go through `get_typed(session, key, Schema)`**, returning a strongly-typed object. Never subscript `get_raw`'s result directly — schema validation is the only barrier stopping one bad edit from taking production down.
2. **Writes are versioned appends**: `set_value` inserts a new `PlatformConfig` version, invalidates the Redis cache, and writes to `AuditLog` (actor, before/after summary, reason). Updating the table directly, bypassing the service, means losing history, losing the audit trail, and a stale cache.
3. **Every config change requires a reason**, and so does `rollback`. High-risk admin operations require a second confirmation (see `zaolang-admin-console`).
4. **Secret fields never enter the general config API**: `llm_providers`'s list/get/update/diff/history/rollback all reject it — only the dedicated model API returns masked values and connectivity status.
5. **Cache invalidation never relies on TTL alone**: both `set_value` and `rollback` call `invalidate(key)`. If Redis is unavailable, the service falls back to reading the database directly (the probe runs inside `begin_nested`, so it never poisons the transaction).
6. **Defaults must let an empty database work.** `DEFAULT_CONFIGS` is what `get_typed` falls back to when the key doesn't exist in the database yet — tests and fresh deployments both depend on it.
7. **Never bring back a routing-score-weight config section.** Which provider wins is decided by `intent_router`'s LLM judgment (`zaolang-agent-gateway` invariant #1), not a tunable number — this module only owns the provider catalogue's hard switches: existence, enablement, and quota limits.
8. **A `get_typed` validation failure falls back to the whole `DEFAULT_CONFIGS["llm_providers"]` (empty `endpoints`)** — one bad endpoint can wipe the entire routing catalogue. So `LlmProviderEndpoint.protocol` must be optional (`None`-able): when the field is missing, `_migrate_legacy_fields` infers it from capabilities (video-only → `minimax`, else → `openai`). `kind=general` always clears `protocol`. An explicit admin upsert is validated strictly: an unimplemented protocol, or `minimax`+image/audio raise `ValidationFailed` (HTTP 422) — silent fallback is never allowed. `openai`+video is now a valid combination (the OpenAI Videos API contract, text-to-video scoped by whatever the target model's schema supports), not just image/audio. Existing endpoints with a cross-protocol mismatch are individually skipped (with a warning logged) inside `LlmProviderConfig`, rather than failing the whole config.
9. **AiHubMix (USD, international channel) and DMXAPI (CNY, domestic channel) never share one default price for the same nominal upstream model.** MiniMax H3 and Doubao Seedance 2.5 each have a catalog entry under both vendors, and the two entries' `price_items` are sourced from that vendor's own actual resale channel — MiniMax's international PAYG page for AiHubMix, its domestic page for DMXAPI; BytePlus ModelArk's international price for AiHubMix, Volcano Ark's domestic price for DMXAPI. `test_model_catalog.py`'s `test_aihubmix_and_dmxapi_never_share_one_price_for_the_same_upstream_model` is a regression test for exactly the mistake of collapsing these back into one shared number. A DMXAPI `price_item.default_micro_usd` is that upstream vendor's own domestic list price, not DMXAPI's real invoiced rate — DMXAPI resells at a markup plus 6% tax (`rmb.dmxapi.cn`'s own "厂商原价 / DMXAPI价格（含税6%）" columns), called out per item in `markup_note`. Every `price_items` entry must carry `pricing_doc_url`. `source_amount`/`markup_note`/`pricing_doc_url` are catalog-authoring metadata and regression-test fixtures only — the admin form no longer renders a "vendor page pricing reference" block or a pricing-source link when an operator picks a known model (removed alongside `knownModelPricingReference`/`knownModelPricingDocLink`); an operator verifying a price against the vendor's own page must look it up directly, not read it off `/admin/models`.
10. **A catalog default only pre-fills a form field the first time an operator picks that model — it never overwrites a price already saved on an existing endpoint** just because the edit dialog reopened. Re-selecting the same model from the picker while editing *does* reapply the preset (same as it already does for protocol/modalities) — that is deliberate, opt-in interaction, not a silent background overwrite.

## Extension Points

**Add a config field**

1. Add the field to the relevant `ConfigSection` in `schemas.py` (**with a default**, or deserializing an existing version breaks).
2. Add the matching field to `DEFAULT_CONFIGS`.
3. Update call sites to read the new field directly — never leave a type-bypassing `getattr(cfg, "x", fallback)`.
4. The frontend's `config-console.tsx` auto-supports it via the JSON editor; sections with a dedicated panel (pricing, flags, short-video) need explicit updates too — `runtime-config-panel.tsx`'s `ShortformForm` is a hand-written field list, not schema-auto-rendered, so a new field needs an explicit control (e.g. `ShortformConfig.enable_clarifying_questions` / `enable_preview_picker` / `preview_candidate_count`, the short-video studio's follow-up-question and preview-picker toggles).
5. Add a unit test to `back/tests/unit/test_platform_config.py`.

**Add a new config section**: add an entry to both `CONFIG_SCHEMAS` and `DEFAULT_CONFIGS` — `all_keys()` picks it up automatically, and it appears in the admin list on its own.

**Add a feature flag**: add a boolean field to `FeatureFlags` → check it at call sites with `is_enabled(session, "flag_name", user_id=...)`. Gradual rollout is hashed by user_id — don't implement your own bucketing. The drama editor's five flags (`drama_studio_enabled` / `web_editor_enabled` / `variant_export_enabled` / `editor_ai_enabled` / `editor_mcp_enabled`) default to false; the last three depend on `web_editor_enabled`. Local `make seed` turns them on — never write that seed behavior into `DEFAULT_CONFIGS`. See `zaolang-editor-drama`.

**Add a known model to the provider picker**: add a `ModelCatalogEntry` to `model_catalog.py`'s `VENDOR_MODEL_CATALOG[vendor]`, with `price_items` sourced from that specific vendor's own actual channel (see invariant #9) — never copy another vendor's entry's numbers even for "the same" upstream model. Convert the vendor's own quoted unit to micro-USD with `_usd_micro_usd`/`_cny_micro_usd` (the latter at the same 7.2 CNY/USD rate the admin form defaults to) and record `source_amount`/`quoted_on`/`pricing_doc_url` verbatim — these three fields document where the number came from for the next editor of this file and for `test_model_catalog.py`, but are not surfaced anywhere in `/admin/models` (see invariant #9). Add coverage to `test_model_catalog.py` (every price item non-negative, a `markup_note` on every DMXAPI item, and — if this is a model that also has an entry under the other vendor — that the two vendors' numbers differ). `GET /admin/llm-providers/catalog` picks the new entry up automatically; the admin form's `VendorModelPicker.applyModel` silently pre-fills the pricing fields from `price_items` by `key`/`dimension` (see `priceItemsToFormPatch` in `llm-providers-panel.tsx`) using the vocabulary `video_generation` / `video_input_material` / `video_extra_reference_image` / `image_generation` / `image_input_reference` / `token_video_no_ref` / `token_video_with_ref` / `llm_input_tokens` / `llm_output_tokens` / `llm_cached_input_tokens` — the operator sees only the resulting numbers in the normal price fields, never a separate reference block.

**Add a fundamentally different billing shape** (not just a new dimension on an existing shape): add the new pricing section to `MediaPricing`/`TokenPricing` in `schemas.py` (optional, default `None`/`0`, dropped by the same capability-coverage rule as `video`/`image`/`audio` in `_media_model_and_modalities_are_coherent`), add the cost function to `costs/service.py`, and branch on a new `billing_profile` string constant inside `media_call_cost_micro_usd`/`llm_call_cost_micro_usd` — mirroring `SEEDANCE_TOKENS_BILLING_PROFILE`. Every existing caller must keep costing exactly as before when it doesn't set the new profile.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/unit/test_platform_config.py tests/unit/test_model_pricing.py tests/unit/test_model_catalog.py tests/integration/test_admin_ops_platform.py tests/integration/test_admin_llm_providers.py -v
```

After changing something, exercise it in admin at `/admin/config`: edit → view the diff → roll back → confirm both actions appear with their reasons in `/admin/audit` (Log Center).

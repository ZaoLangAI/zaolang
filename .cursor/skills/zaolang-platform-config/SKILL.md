---
name: zaolang-platform-config
description: Versioned, audited runtime config and feature flags — CONFIG_SCHEMAS/DEFAULT_CONFIGS, get_typed/set_value/rollback, llm_providers endpoint schema, micro-USD vendor pricing. Use when adding a config field or feature flag, changing model prices, or debugging a config change that did not apply.
---

# Runtime Config & Feature Flags

**Scope**: typed, versioned, rollback-capable config sections (`CONFIG_SCHEMAS`), feature flags, `llm_providers` schema, vendor price math. Agent↔model bindings live on `AgentProfile`.
Not here → `zaolang-agent-gateway` (providers, routing), `zaolang-admin-console` (config UI), `zaolang-credits-billing` (user credit prices).

## Key Paths

| Path | What |
|---|---|
| `back/app/platform_config/schemas.py` | `CONFIG_SCHEMAS` (`pricing`, `royalty`, `marketplace`, `feature_flags`, `content`/`learning`/`skill_moderation`, `shortform`, `llm_providers`), `DEFAULT_CONFIGS`, `FeatureFlags`/`FEATURE_FLAG_NAMES`, `LlmProviderEndpoint`, `MediaPricing`, `VIDEO_RESOLUTIONS` |
| `back/app/platform_config/service.py` | `get_typed` / `get_raw` / `set_value` / `rollback` / `history` / `invalidate` / `is_enabled` |
| `back/app/api/v1/admin/config.py` | generic config API (read `Viewer`+`AdminRead`; `PUT` `Admin`+`AdminWrite`, audit `config.update`; rollback `Admin`+`AdminDangerous`, audit `config.rollback`); `FLAG_DESCRIPTIONS`; `GENERIC_CONFIG_KEYS` excludes `llm_providers` |
| `back/app/api/v1/admin/llm_providers.py` | masked endpoint CRUD, validate, `GET /v1/admin/llm-providers/catalog` |
| `back/app/domain/costs/service.py` | per-call vendor cost in micro-USD; `SEEDANCE_TOKENS_BILLING_PROFILE` |
| `back/app/providers/model_catalog.py` | per-vendor `price_items` for the admin model picker |
| `front/src/components/admin/config/runtime-config-panel.tsx` | hand-built forms (flags, shortform, pricing, royalty, marketplace, moderation) + Advanced JSON |
| `front/src/components/admin/models/llm-providers-panel.tsx` | `/admin/models`; `VendorModelPicker`, `priceItemsToFormPatch` |
| `front/src/lib/admin/micro-usd.ts` | USD/CNY string ↔ micro-USD integer conversion for admin pricing and statistics |

## Invariants

1. Read only via `get_typed(session, key, Schema)`; a stored value that fails validation falls back to the **whole** `DEFAULT_CONFIGS[key]`. `service.get_typed`
2. Therefore `LlmProviderConfig` is lenient per endpoint: `LlmProviderEndpoint._migrate_legacy_fields` upgrades old shapes (`models`/`priority`/`capabilities`) and infers a missing media `protocol` (`infer_media_protocol`); `_drop_invalid_endpoints` skips a still-invalid endpoint with a warning; `_healed_media_timeout` lifts stored image timeouts to the floor. Explicit admin upserts are strict (422).
3. `set_value` deactivates the active row and inserts version N+1, then `invalidate(key)`; rollback = a new version copying the old value. Never edit `PlatformConfig` rows by hand. `AuditLog` is written by admin handlers (`audit.record`), not the service — scripts leave no audit row.
4. Every write/rollback needs a non-empty reason (`ConfigUpdateRequest.note`; rollback `ConfigRollbackRequest` = `DangerousAction` + `require_confirmation`).
5. Values are cached in Redis for `CACHE_TTL_SECONDS` (30); Redis errors are swallowed (`_try_cache_get`/`_try_cache_set`/`invalidate`) and reads fall through to Postgres, so a failed invalidate is stale ≤ 30 s.
6. Every new field needs a default in the schema and `DEFAULT_CONFIGS` — empty DBs and tests depend on it.
7. `llm_providers` never goes through the generic config API; secrets only via the masked `/admin/llm-providers` API.
8. Feature flags (owner): source of truth is `FeatureFlags`; check with `is_enabled(session, name, user_id=)`. `rollout_percentages` is validated per flag (not `public_registration`) and hashes `user_id`; a partial rollout is `False` when `user_id` is omitted — don't add a second bucketing path. `FLAG_DESCRIPTIONS` must cover `FEATURE_FLAG_NAMES` (`test_admin_ops_platform.py`).
9. Flag dependencies live in the gates, not the schema: editor sub-flags require `web_editor_enabled` (`back/app/domain/editor/flags.py:require_flag`); `blocking_studio_enabled` also needs `script_studio_enabled` (`back/app/domain/blocking/service.py:is_enabled`). Off-gates raise `NotFound`.
10. `make seed` (`_seed_editor_flags`) turns creation flags on locally — never copy that into `DEFAULT_CONFIGS` (creation flags default off).
11. Money is integer micro-USD. Front converts decimal strings (no float multiply); CNY needs an explicit rate — `DEFAULT_CNY_PER_USD` (7.2) only seeds the form, an invalid rate/price is rejected, never coerced. `front/src/lib/admin/micro-usd.ts`
12. Vendor prices are per `(vendor, model)`, never shared across vendors for one upstream model; vendors = `VENDOR_IDS` (aihubmix/dmxapi/metaso/fal); an entry with `price_items` needs an entry-level `pricing_doc_url`; DMXAPI items carry `markup_note`, Metaso's don't. `back/tests/unit/test_model_catalog.py`
13. Catalog prices pre-fill only when an operator picks a model; reopening never overwrites saved prices.
14. `billing_profile` is metadata; only `SEEDANCE_TOKENS_BILLING_PROFILE` changes cost math.
15. No routing-weight config — provider choice is the LLM's (see `zaolang-agent-gateway` › routing). `AgentModelBinding` in `schemas.py` is dead; don't wire it up.

## Recipes

**Add a config field**: field with default on the `ConfigSection` → `DEFAULT_CONFIGS` → read it typed (no `getattr` fallback) → explicit control in `runtime-config-panel.tsx` → test in `back/tests/unit/test_platform_config.py`. New section: add to both `CONFIG_SCHEMAS` and `DEFAULT_CONFIGS` (`all_keys()` picks it up).

**Add a feature flag**: bool on `FeatureFlags` (staged surfaces default `False`) → `FLAG_DESCRIPTIONS` label + expected set in `test_platform_config.py` → gate with `is_enabled` → UI entry: `MeFeaturesResponse` in `back/app/api/v1/auth.py:_features_for` → `_seed_editor_flags` if dev needs it on.

**Add a priced model**: `ModelCatalogEntry` in `VENDOR_MODEL_CATALOG[vendor]` with `price_items` from that vendor's own page (`_usd_micro_usd`/`_cny_micro_usd`, `source_amount`, `quoted_on`, `pricing_doc_url`) → coverage in `test_model_catalog.py`. A new billing shape: optional section on `MediaPricing`/`TokenPricing` + cost fn + new `billing_profile` branch; existing callers must cost unchanged.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/unit/test_platform_config.py tests/unit/test_model_pricing.py tests/unit/test_model_catalog.py tests/integration/test_admin_ops_platform.py tests/integration/test_admin_llm_providers.py -v
cd front && npm run test -- src/lib/admin/micro-usd.test.ts
```
Manual: `/admin/config` edit → diff → rollback; both appear in `/admin/audit`.

---
name: zaolang-agent-gateway
description: Agno agents, LLM client/failover, provider routing (hard filter + intent_router pick), media adapters and their quirks, tool whitelist, agent_skills slots, prompt polish (/generation/prompts/enhance), /gateway/status. Use when editing back/app/agents, llm, providers, teams or copy coaches.
---

# Agent Gateway & LLM Access

**Scope**: agents own judgment (safety/planner/quality/intent_router) or assist (copy); providers own production. `router.route()` hard-filters in code, `intent_router.select_provider()` (LLM) picks. Plus LLM client, media adapters, prompt slots, prompt polish, gateway status.
Not here → `zaolang-generation-jobs` (pipeline, fast-retry seeding, SSE), `zaolang-platform-config` (`llm_providers` schema, pricing, flags), `zaolang-editor-drama` (`editor_planner`, script writing), `zaolang-canvas` (`canvas_planner`), `zaolang-blocking-studio` (`blocking_director`), `zaolang-creation-library` (skill_matcher's drama/format skills).

## Key Paths

| Path | What |
|---|---|
| `back/app/agents/router.py` | `build_catalog` / `route()` / `Candidate` / `RoutingDecision` / `record_attempt_outcome`; hard filters only, no scoring |
| `back/app/agents/intent_router.py` | `select_provider()` (LLM pick, `SELECT_PROVIDER_SYSTEM_PROMPT`), `classify()` (tier, downgrade-only) |
| `back/app/agents/base.py` | `run_agent` / `run_agent_stream` / debug variants; binding resolution; writes `AgentRun` |
| `back/app/agents/tools.py` | `TOOL_REGISTRY` + `AGENT_TOOL_GRANTS` — the only way an agent reaches domain services |
| `back/app/agents/slots.py` | `PROMPT_SLOTS[role]` — every role's named system-prompt slots |
| `back/app/agents/safety.py`, `planner.py`, `quality.py`, `copywriter.py`, `custom.py` | core roles; `custom.py` runs the `custom_agent` node (role from `config.agent_role`) |
| `back/app/agents/scene_skills.py`, `questions.py`, `skill_matcher.py` | scene space-type packs; shared follow-up question sanitizer; drama reference-skill matcher |
| `back/app/agents/agent_os.py`, `back/app/teams/generation_gateway.py` | AgentOS mount; console-only Team (production runs `app.workers.pipeline`) |
| `back/app/domain/agent_skills/` | `service.py` (`resolve_prompt`, `resolve_copy_agent_id`), `presets.py` (`ROLE_PRESETS`), `templates.py` (`SKILL_TEMPLATES`) |
| `back/app/llm/` | `client.py` (`complete`/`stream_complete`/`call_gateway_once`/`probe`), `failover.py`, `normalize.py`, `capabilities.py`, `model_defaults.py` |
| `back/app/providers/model_catalog.py` voice fields | `ModelCatalogEntry.voices` (roster), `voice_params` (`speed` tts-1/tts-1-hd, `emotion` tts-pro) + `voice_emotions`; `voice_capabilities(model)`; adapters forward `extra.speed` only for tts-1/tts-1-hd (clamped to `VOICE_SPEED_RANGE`) |
| `back/app/providers/` | `base.py` (capability, resolution tiers), `media_endpoints.py`, adapters, `media_breaker.py`, `model_catalog.py`, `connectivity.py` |
| `back/app/domain/prompts.py` | prompt-polish domain: `PromptContext`, `PromptEnhancement`, `matched_reference_skills`, `PROMPT_ENHANCE_MAX_LENGTH`=4096 |
| `back/app/api/v1/prompts.py` | `POST /v1/generation/prompts/enhance` — SSE (`matched`→`thinking`/`delta`→`complete`/`error`), no flag |
| `back/app/api/v1/prompt_enhance.py` | helpers (`context_from`, `question_views`); no routes |
| `back/app/api/v1/gateway.py` | `GET /v1/gateway/status` — public aggregate (routes, `savings_percent`, degraded `AgentRun`s 24h) from `build_catalog`/`AgentRun`/`ProviderStat` |
| `back/tests/fake_llm_gateway.py` | autouse offline fake for `llm_client.complete`/`stream_complete`; `_dispatch` per agent |

## Invariants

1. Routing: filtering is code, choosing is the LLM. `route()` sets `filter_reason` (op/tier/duration/aspect/resolution/reference-mode unsupported, `edit_model_requires_video_source`, 白膜 motion guide → `edit_model_not_for_motion_guide`/`video_reference_not_supported`, `music_style_not_supported` for `extra.audio_style`, latency, `previously_failed_this_job`, `provider_circuit_open`); survivors go to `select_provider`. LLM unavailable/off-list → `selected=None`, `reason="llm_selection_unavailable"`. No weighted formula/`routing_weights`; soft preferences live only in `SELECT_PROVIDER_SYSTEM_PROMPT`. `back/app/agents/router.py:route`
2. `Candidate` stats (`success_rate`, latency, `effective_cost_micro_usd`, `estimated_cost_micro_usd`, `model`) are LLM input + admin replay only; no code sorts on them. `quality_prior` is a flat `_QUALITY_PRIOR` — never add a model→score table. `router._candidate_payload`
3. `success_rate` = Beta-smoothed with 0.8 prior over `PRIOR_PSEUDO_SAMPLES`=8; effective cost × `RETRY_COST_AMPLIFICATION`=1.2. `router._success_rate`
4. Every filtered candidate's reason is persisted (`ProviderAttempt`/decision record) for admin replay.
5. `forced_model` (studio "指定模型"): same hard filter, then first survivor by `provider` name matching `model_or_workflow`; none → `reason="forced_model_unavailable"`, no fallback to the LLM pick. `router.route`
6. Resolution is a ceiling, adapted not filtered: `adapt_resolution_tier` → exact / highest strictly lower / last-resort lowest; never 1080p→2K. `resolution_not_supported` only when a candidate maps to no studio tier. Cost + provider call use the adapted vendor literal. `back/app/providers/base.py:adapt_resolution_tier`
7. Media circuit breaker is a hard filter, never a score: 5 counted failures → 120s open → one `SET NX` half-open probe; keys `mediafo:brk:*` (LLM pool uses `llmfo:brk:*`); Redis errors fail open. `back/app/providers/media_breaker.py`
8. One gateway mode: real call or `ProviderTemporaryFailure` (unbound, no endpoint, all failed). No default model, no prod stub; tests use the fake gateway, opt out with `@pytest.mark.live` / `@pytest.mark.real_gateway_seams`. `back/app/llm/client.py:complete`
9. Every agent call writes an `AgentRun` (tokens, latency, `degraded`, `input_json`, `thinking_text`); thinking never goes in `output_json`. `back/app/agents/base.py`
10. `AgentRun.node_id` is written by `WorkflowRunner` diffing `ctx.state["_last_agent_run_id"]` around each executor — agent functions never take `node_id`. `back/app/workflows/runner.py`
11. Normalization never skipped: strip thinking, extract outermost JSON, repair-retry before degrading. Caller `max_tokens` is a floor: `max(max_tokens, binding.max_tokens)`. `back/app/llm/normalize.py`, `base.run_agent`
12. Transport is always streamed (`_stream_gateway`, wall clock `STREAM_WALL_CLOCK_TIMEOUT_SECONDS`=600; thinking resets only the idle timeout); `complete()` still returns one result. One same-endpoint retry (with `retry_nudge`) on thinking-only timeout or `is_usable` failure; no mid-stream failover once a chunk is emitted. Admin「验证有效」stays non-streaming (`call_gateway_once`). `back/app/llm/client.py:stream_complete`
13. Agents touch domain only via `tools.py` with narrow signatures, never a session/SQL. Grants: `planner` → `price_operation`/`list_provider_capabilities`/`lookup_source_parameters`; `copy` → `suggest_tags`; `editor_planner` → `timeline_summary`/`lookup_shortform_profile`/`lookup_media_analysis`; `safety`, `quality`, `intent_router`, `canvas_planner` deliberately empty. `back/app/agents/tools.py:AGENT_TOOL_GRANTS`
14. Roles come only from `ROLE_PRESETS` (= `AgentName`: seven roles); helper agents (`skill_matcher`, `blocking_director`, `character_profile` — slots `character_describe` / `voice_match`) run as role `copy` with their own slot, not a new role. Nodes bind `AgentProfile.id` (never name); role mismatch fails publish (`workflow_templates.service._binding_errors`) and falls back to role default at runtime.
15. LLM failover (`llm/failover.py`, `kind="general"`) and media routing (`kind="media"`) never mix; a bound profile fails over only default↔backup.
16. Quality judges metadata only (it cannot see media); prompt-text durations / missing width are not defects. A new `output_summary` field a model could misread needs a prompt note. `tests/unit/test_quality_duration_gate.py`
17. Prompt polish: degraded copy agent → `error` frame with `ENHANCE_UNAVAILABLE_MESSAGE`, never echo the input as a polish; drama reference skills are video-only and advisory (empty on any failure). `back/app/domain/prompts.py`
18. Secrets only via the masked `/admin/models` API — never config API, logs or prompts. No embedding model here (see `zaolang-discovery-search`).

Cross-job exclusion: see `zaolang-generation-jobs › fast-retry`.

## Recipes

**Add an agent/role**: `ROLE_PRESETS` entry (`judgment`/`assist`) + `SKILL_TEMPLATES` entry → `PROMPT_SLOTS[role]` → module with `SYSTEM_PROMPT` calling `run_agent(..., slot=)` → node type or `custom_agent` → grant in `AGENT_TOOL_GRANTS` → branch in `fake_llm_gateway._dispatch`.

**Add a slot**: `PromptSlot` in `slots.py` → constant + `run_agent(slot=)`/`run_agent_stream` → template → domain wrapper or node `AgentBinding`. Copy slots get no editor tab (inferred from `default_for_asset_kind`).

**Change provider selection**: edit `SELECT_PROVIDER_SYSTEM_PROMPT` (or publish an `AgentSkill`) and sync `fake_llm_gateway._intent_router`. Never add sorting to `router.py`.

**Add a media provider**: config-only if the contract matches an implemented protocol (`/admin/models`, `kind="media"`) + `VENDOR_MODEL_CATALOG` entry. New contract → new `GenerationProvider`, `media_endpoints._factory` branch, `IMPLEMENTED_MEDIA_PROTOCOLS`, `connectivity.py` probe (cancel it if billable). See `reference-providers.md`.

**Add an agent tool**: `tools.py` function → `TOOL_REGISTRY` → grant; label in `front/src/lib/admin/tool-grants.ts`.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/unit/test_agent_gateway.py tests/unit/test_media_routing.py tests/unit/test_media_breaker.py tests/unit/test_llm_normalize.py tests/unit/test_llm_gateway_failover.py tests/unit/test_llm_failover_lease.py tests/unit/test_llm_capabilities.py tests/unit/test_prompt_enhance.py tests/unit/test_agent_questions.py tests/unit/test_scene_skills.py tests/unit/test_skill_matcher.py tests/unit/test_quality_duration_gate.py tests/integration/test_prompts_api.py -v
cd back && conda run -n zaolang pytest tests/unit/test_aihubmix_media.py tests/unit/test_dmxapi_media.py tests/unit/test_minimax_v2_media.py tests/unit/test_fal_media.py tests/unit/test_model_catalog.py tests/unit/test_provider_connectivity.py -v
make test-llm   # live smoke, real keys, not in make check
```

## References

- `reference-providers.md` — read when touching a media adapter, protocol, model profile, probe, catalog entry, or debugging an upstream 400/poll.
- `reference-prompts.md` — read when editing copy coaches, character-sheet/scene prompts, scene skill packs, follow-up questions or seeded agent prompts.

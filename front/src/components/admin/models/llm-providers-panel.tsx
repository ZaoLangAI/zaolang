'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useId, useRef, useState } from 'react';

import { useAdminSession } from '@/components/admin/admin-session-provider';
import { DangerConfirm } from '@/components/admin/danger-confirm';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Select, TextInput } from '@/components/ui/field';
import { IconFlask, IconPencil, IconRefresh, IconTrash } from '@/components/ui/icons';
import { Badge, EmptyState, ErrorNotice } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import {
  DEFAULT_CNY_PER_USD,
  type PriceInputCurrency,
  convertDisplayPrice,
  displayToMicroUsd,
  dollarsToMicroUsd,
  microUsdToDisplay,
  microUsdToDollars,
  parseCnyPerUsd,
} from '@/lib/admin/micro-usd';
import { formatTokenCount, parseTokenCount } from '@/lib/admin/token-count';
import { cn } from '@/lib/cn';
import {
  AUDIO_GENERATION_KINDS,
  AUDIO_GENERATION_KIND_LABEL_KEYS,
  GENERAL_INPUT_MODALITIES,
  MEDIA_INPUT_MODALITIES,
  MEDIA_OUTPUT_MODALITIES,
  MEDIA_PROTOCOLS,
  IMPLEMENTED_MEDIA_PROTOCOLS,
  MODALITY_LABEL_KEYS,
  OPERATION_LABEL_KEYS,
  PROTOCOL_LABEL_KEYS,
  capabilitiesForModalities,
  constrainModalities,
  operationLabelKey,
} from '@/lib/admin/operations';
import type {
  AudioGenerationKindValue,
  GeneralInputModality,
  MediaInputModality,
  MediaOutputModality,
  MediaProtocol,
} from '@/lib/admin/operations';
import { atLeast } from '@/lib/admin/rbac';
import { adminApi } from '@/lib/api/admin-client';
import type {
  LlmProviderEndpoint,
  LlmProviderKind,
  LlmProviderPool,
  LlmProviderValidationJob,
  LlmProviderValidationResult,
  ModelCatalogEntry,
  ModelCatalogResponse,
  PriceItem,
} from '@/lib/api/admin-types';
import { ApiError } from '@/lib/api/errors';

/** `"custom"` means "type everything by hand" — today's behaviour,
 * unchanged. Any other value narrows the model field to that vendor's known
 * catalogue (see `ModelCatalogResponse`), purely as a form-filling
 * convenience: nothing here is sent to the API or enforced at save time.
 * Mirrors backend `model_catalog.VendorId`; hand-kept in sync like every
 * other enum this file already mirrors (e.g. `MediaProtocol`). */
type VendorChoice = 'custom' | 'aihubmix' | 'dmxapi' | 'metaso' | 'fal';
const CUSTOM_VENDOR: VendorChoice = 'custom';

/** Mirrors `app.domain.costs.service.SEEDANCE_TOKENS_BILLING_PROFILE` — the
 * one `billing_profile` value the cost code actually branches on, to bill
 * `token_video`'s per-million-token formula instead of the per-second
 * `video_generation`/`video_input_material` fields. An endpoint on this
 * profile never reads those per-second fields at settlement, so the form
 * hides that whole block for it rather than showing price inputs that would
 * silently do nothing. */
const SEEDANCE_TOKENS_BILLING_PROFILE = 'seedance_tokens';

/**
 * Which `VIDEO_RESOLUTIONS`/`IMAGE_TIERS` keys the currently selected known
 * model actually looks up at settlement — derived from its catalog
 * `price_items`' own `dimension`s, not the full fixed list every vendor's
 * casing convention happens to share space in. `null` means "unknown model
 * (custom, or a known model with no declared items for this key)" — show
 * every key rather than guessing which one a hand-typed endpoint needs.
 */
/** Looks up the catalog entry for whatever vendor/model the form currently
 * has selected, so the pricing block can tell a known model's own declared
 * price items from a hand-typed custom one. Not scoped to `kind` — the
 * caller already narrows `model` to one vendor+kind combination via the
 * picker, and two different kinds never share a model id in practice. */
function findCatalogEntry(
  catalog: ModelCatalogResponse,
  vendor: VendorChoice,
  model: string,
): ModelCatalogEntry | undefined {
  if (vendor === CUSTOM_VENDOR || !model.trim()) return undefined;
  return catalog.vendors
    ?.find((item) => item.vendor === vendor)
    ?.models?.find((entry) => entry.model === model);
}

function relevantDimensions(entry: ModelCatalogEntry | undefined, keys: string[]): Set<string> | null {
  if (!entry) return null;
  const dims = new Set(
    (entry.price_items ?? [])
      .filter((item) => keys.includes(item.key) && item.dimension)
      .map((item) => item.dimension),
  );
  return dims.size > 0 ? dims : null;
}

/**
 * Prices are held as the decimal strings the operator typed in the current
 * display currency (USD or CNY), not as numbers. Parsing on every keystroke
 * would fight the caret: `"0."` is not yet a number, and formatting a parsed
 * zero yields `""`, which would erase the decimal point as it was typed.
 * Conversion to micro-USD happens once, on save.
 */
interface EndpointFormState {
  id: string;
  name: string;
  base_url: string;
  api_key: string;
  kind: LlmProviderKind;
  // Which known-model catalogue to offer for the model field below —
  // `"custom"` means free text, exactly like every endpoint before this
  // picker existed. Never sent to the API.
  vendor: VendorChoice;
  // The one model id this endpoint serves, whatever its kind.
  model: string;
  input_modalities: MediaInputModality[];
  output_modalities: MediaOutputModality[];
  protocol: MediaProtocol;
  generation_kind: 'create' | 'edit';
  // `kind="media"` only: which `text -> audio` capability this endpoint's
  // model serves when the modality pair alone is ambiguous — see
  // `AUDIO_GENERATION_KINDS`. Ignored (and hidden) otherwise.
  audio_generation_kind: AudioGenerationKindValue;
  role: 'primary' | 'backup';
  backup_order: string;
  max_concurrency: string;
  timeout_ms: string;
  enabled: boolean;
  // Which `app.providers.model_catalog` billing shape this endpoint's
  // prices follow — copied from the picked catalog entry, or `null` for a
  // hand-typed custom model. Purely metadata: nothing on this form branches
  // on it, `app.domain.costs.service` does.
  billing_profile: string | null;
  // `kind="general"` pricing and limits.
  context_length: string;
  max_output_tokens: string;
  input_per_million: string;
  output_per_million: string;
  // A prompt-cache hit, billed below the regular input rate (declared here
  // even though nothing parses a live cache-hit count yet — see
  // `TokenPricing.cached_input_per_million_micro_usd`).
  cached_input_per_million: string;
  // `kind="media"` pricing, by section.
  image_input: string;
  image_generation: string;
  // Doubao Seedream-style size-tiered generation price (keyed "1K"/"2K");
  // falls back to `image_generation` for a tier this map does not cover.
  image_generation_by_tier: Record<string, string>;
  image_reference_free_count: string;
  audio_per_10k: string;
  music_per_request: string;
  video_generation: Record<string, string>;
  video_input_material: Record<string, string>;
  video_reference_free_count: string;
  video_extra_reference: string;
  // Doubao Seedance-style per-million-video-token billing — the alternate
  // shape a `billing_profile="seedance_tokens"` endpoint uses instead of
  // the per-second `video_generation` fields above.
  token_video_no_ref: string;
  token_video_with_ref: string;
}

/** Mirrors `VIDEO_RESOLUTIONS` in `app/platform_config/schemas.py`; the API
 * rejects any other key, so the form offers exactly these. Casing is exactly
 * what each vendor's own API expects (never normalised) — DMXAPI's doubao
 * models answer lowercase, its `wan3.0-video` answers uppercase, MiniMax
 * stays `768P`/`2K`. */
const VIDEO_RESOLUTIONS = [
  '2K',
  '768P',
  '480p',
  '720p',
  '1080p',
  '480P',
  '720P',
  '1080P',
] as const;

function emptyResolutionPrices(): Record<string, string> {
  return Object.fromEntries(VIDEO_RESOLUTIONS.map((resolution) => [resolution, '']));
}

function resolutionPricesFrom(prices: Record<string, number> | undefined): Record<string, string> {
  return Object.fromEntries(
    VIDEO_RESOLUTIONS.map((resolution) => [
      resolution,
      microUsdToDollars(prices?.[resolution] ?? 0),
    ]),
  );
}

/** Mirrors `generation_per_image_by_tier_micro_usd`'s keys — Doubao
 * Seedream's own size-tier vocabulary. Kept separate from
 * `VIDEO_RESOLUTIONS` since a vendor's image tiers and video resolutions are
 * unrelated dimensions that happen to share the "1K/2K/4K" shorthand. */
const IMAGE_TIERS = ['1K', '2K', '4K'] as const;

function emptyTierPrices(): Record<string, string> {
  return Object.fromEntries(IMAGE_TIERS.map((tier) => [tier, '']));
}

function tierPricesFrom(prices: Record<string, number> | undefined): Record<string, string> {
  return Object.fromEntries(
    IMAGE_TIERS.map((tier) => [tier, microUsdToDollars(prices?.[tier] ?? 0)]),
  );
}

type ValidationInFlight = {
  validationId: string;
  startedAt: number;
  timeoutMs: number;
};

function delay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException('Aborted', 'AbortError'));
      return;
    }
    const timer = window.setTimeout(resolve, ms);
    signal.addEventListener(
      'abort',
      () => {
        window.clearTimeout(timer);
        reject(new DOMException('Aborted', 'AbortError'));
      },
      { once: true },
    );
  });
}

function isAbortError(caught: unknown): boolean {
  return (
    (caught instanceof DOMException && caught.name === 'AbortError') ||
    (caught instanceof Error && caught.name === 'AbortError')
  );
}

/**
 * Model ids are no longer admin-authored: the endpoint id is just the config
 * dict key, so a random id is exactly as good as a hand-picked slug and
 * removes an input the admin has no reason to think about. `ep_` mirrors the
 * repo's typed-id-prefix convention even though this key never touches
 * `back/app/models/base.py:new_id` — it lives in `PlatformConfig` JSON, not a
 * database row.
 *
 * Built from `crypto.getRandomValues` rather than `randomUUID`: the latter is
 * only defined in a secure context, so opening this dialog over plain
 * `http://` (e.g. a LAN IP during local dev) threw before `setEditing` ever
 * ran, leaving the "add model" button silently inert. `Math.random` is the
 * final fallback for environments without `crypto` at all — this id is not a
 * secret, so a weaker source is an acceptable trade for the dialog opening.
 */
function randomHex(byteLength: number): string {
  const bytes = new Uint8Array(byteLength);
  if (typeof globalThis.crypto?.getRandomValues === 'function') {
    globalThis.crypto.getRandomValues(bytes);
  } else {
    for (let i = 0; i < bytes.length; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  }
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

function generateModelId(existingIds: Set<string>): string {
  for (let attempt = 0; attempt < 5; attempt += 1) {
    const id = `ep_${randomHex(6)}`;
    if (!existingIds.has(id)) return id;
  }
  return `ep_${randomHex(12)}`;
}

function emptyForm(id: string, kind: LlmProviderKind, hasPrimary: boolean): EndpointFormState {
  return {
    id,
    name: '',
    base_url: '',
    api_key: '',
    kind,
    vendor: CUSTOM_VENDOR,
    model: '',
    input_modalities: kind === 'general' ? ['text'] : [],
    output_modalities: [],
    protocol: 'openai',
    generation_kind: 'create',
    audio_generation_kind: 'voice',
    role: !hasPrimary ? 'primary' : 'backup',
    backup_order: '100',
    max_concurrency: '4',
    timeout_ms: kind === 'media' ? '90000' : '30000',
    enabled: true,
    billing_profile: null,
    context_length: '',
    max_output_tokens: '',
    input_per_million: '',
    output_per_million: '',
    cached_input_per_million: '',
    image_input: '',
    image_generation: '',
    image_generation_by_tier: emptyTierPrices(),
    image_reference_free_count: '0',
    audio_per_10k: '',
    music_per_request: '',
    video_generation: emptyResolutionPrices(),
    video_input_material: emptyResolutionPrices(),
    video_reference_free_count: '5',
    video_extra_reference: '',
    token_video_no_ref: '',
    token_video_with_ref: '',
  };
}

function formFrom(endpoint: LlmProviderEndpoint): EndpointFormState {
  const tokens = endpoint.token_pricing;
  const media = endpoint.media_pricing;
  return {
    id: endpoint.id,
    name: endpoint.name,
    base_url: endpoint.base_url,
    api_key: '',
    kind: endpoint.kind,
    // Editing an existing endpoint always starts on "custom": its real,
    // already-saved values are shown as-is. The operator can still switch
    // to a vendor afterwards to re-apply a preset over them.
    vendor: CUSTOM_VENDOR,
    model: endpoint.model ?? '',
    input_modalities: (endpoint.input_modalities ?? []) as MediaInputModality[],
    output_modalities: (endpoint.output_modalities ?? []) as MediaOutputModality[],
    protocol: endpoint.kind === 'media' && endpoint.protocol ? endpoint.protocol : 'openai',
    generation_kind: endpoint.generation_kind === 'edit' ? 'edit' : 'create',
    audio_generation_kind: endpoint.audio_generation_kind === 'music' ? 'music' : 'voice',
    role: endpoint.role,
    backup_order: String(endpoint.backup_order),
    max_concurrency: String(endpoint.max_concurrency),
    timeout_ms: String(endpoint.timeout_ms),
    enabled: endpoint.enabled,
    billing_profile: endpoint.billing_profile ?? null,
    context_length: formatTokenCount(endpoint.context_length),
    max_output_tokens: formatTokenCount(endpoint.max_output_tokens),
    input_per_million: microUsdToDollars(tokens?.input_per_million_micro_usd ?? 0),
    output_per_million: microUsdToDollars(tokens?.output_per_million_micro_usd ?? 0),
    cached_input_per_million: microUsdToDollars(tokens?.cached_input_per_million_micro_usd ?? 0),
    image_input: microUsdToDollars(media?.image?.input_per_image_micro_usd ?? 0),
    image_generation: microUsdToDollars(media?.image?.generation_per_image_micro_usd ?? 0),
    image_generation_by_tier: tierPricesFrom(media?.image?.generation_per_image_by_tier_micro_usd),
    image_reference_free_count: String(media?.image?.reference_image_free_count ?? 0),
    audio_per_10k: microUsdToDollars(media?.audio?.per_10k_characters_micro_usd ?? 0),
    music_per_request: microUsdToDollars(media?.music?.per_request_micro_usd ?? 0),
    video_generation: resolutionPricesFrom(media?.video?.generation_per_second_micro_usd),
    video_input_material: resolutionPricesFrom(media?.video?.input_material_per_second_micro_usd),
    video_reference_free_count: String(media?.video?.reference_image_free_count ?? 5),
    video_extra_reference: microUsdToDollars(media?.video?.extra_reference_image_micro_usd ?? 0),
    token_video_no_ref: microUsdToDollars(media?.token_video?.per_million_tokens_micro_usd ?? 0),
    token_video_with_ref: microUsdToDollars(
      media?.token_video?.per_million_tokens_with_video_ref_micro_usd ?? 0,
    ),
  };
}

/** Every price field on the form, so validation and payload building agree on
 * what has to parse. */
function priceFields(form: EndpointFormState): string[] {
  return form.kind === 'general'
    ? [form.input_per_million, form.output_per_million, form.cached_input_per_million]
    : [
        form.image_input,
        form.image_generation,
        form.audio_per_10k,
        form.music_per_request,
        form.video_extra_reference,
        form.token_video_no_ref,
        form.token_video_with_ref,
        ...Object.values(form.video_generation),
        ...Object.values(form.video_input_material),
        ...Object.values(form.image_generation_by_tier),
      ];
}

/** Shared by the per-resolution video fields and the per-tier image fields:
 * only a key the operator actually priced is sent, so a zero never claims
 * the vendor charges nothing for a dimension nobody has filled in yet. */
function keyedPricePayload(
  prices: Record<string, string>,
  keys: readonly string[],
  currency: PriceInputCurrency,
  rateMicro: number,
): Record<string, number> {
  const payload: Record<string, number> = {};
  for (const key of keys) {
    const micros = displayToMicroUsd(prices[key] ?? '', currency, rateMicro);
    if (micros) payload[key] = micros;
  }
  return payload;
}

function resolutionPricePayload(
  prices: Record<string, string>,
  currency: PriceInputCurrency,
  rateMicro: number,
): Record<string, number> {
  return keyedPricePayload(prices, VIDEO_RESOLUTIONS, currency, rateMicro);
}

function tierPricePayload(
  prices: Record<string, string>,
  currency: PriceInputCurrency,
  rateMicro: number,
): Record<string, number> {
  return keyedPricePayload(prices, IMAGE_TIERS, currency, rateMicro);
}

/** Rewrites every price field when the operator toggles USD ↔ CNY. Invalid
 * or mid-keystroke strings stay put (`convertDisplayPrice`). */
function convertFormPrices(
  form: EndpointFormState,
  from: PriceInputCurrency,
  to: PriceInputCurrency,
  rateMicro: number,
): Pick<
  EndpointFormState,
  | 'input_per_million'
  | 'output_per_million'
  | 'cached_input_per_million'
  | 'image_input'
  | 'image_generation'
  | 'image_generation_by_tier'
  | 'audio_per_10k'
  | 'music_per_request'
  | 'video_generation'
  | 'video_input_material'
  | 'video_extra_reference'
  | 'token_video_no_ref'
  | 'token_video_with_ref'
> {
  const convert = (value: string) => convertDisplayPrice(value, from, to, rateMicro);
  const convertKeyed = (prices: Record<string, string>, keys: readonly string[]) =>
    Object.fromEntries(keys.map((key) => [key, convert(prices[key] ?? '')]));
  return {
    input_per_million: convert(form.input_per_million),
    output_per_million: convert(form.output_per_million),
    cached_input_per_million: convert(form.cached_input_per_million),
    image_input: convert(form.image_input),
    image_generation: convert(form.image_generation),
    image_generation_by_tier: convertKeyed(form.image_generation_by_tier, IMAGE_TIERS),
    audio_per_10k: convert(form.audio_per_10k),
    music_per_request: convert(form.music_per_request),
    video_generation: convertKeyed(form.video_generation, VIDEO_RESOLUTIONS),
    video_input_material: convertKeyed(form.video_input_material, VIDEO_RESOLUTIONS),
    video_extra_reference: convert(form.video_extra_reference),
    token_video_no_ref: convert(form.token_video_no_ref),
    token_video_with_ref: convert(form.token_video_with_ref),
  };
}

/** Shared shape for `PUT /admin/llm-providers/{id}`, used both by the full
 * editor save and by the list row's quick enable/disable toggle so the two
 * never drift on what a "no-op except one field" write looks like. */
function buildUpsertPayload(
  form: EndpointFormState,
  currency: PriceInputCurrency = 'USD',
  rateMicro = 1,
) {
  const micros = (value: string) => displayToMicroUsd(value, currency, rateMicro) ?? 0;
  return {
    name: form.name,
    base_url: form.base_url,
    api_key: form.api_key.trim() ? form.api_key.trim() : undefined,
    kind: form.kind,
    role: form.role,
    backup_order: Number(form.backup_order),
    model: form.model.trim(),
    // Both kinds send their own input-modality selection now — the server
    // auto-injects "text" for general regardless, so this only needs to
    // reflect what's shown to the admin.
    input_modalities: form.input_modalities,
    output_modalities: form.kind === 'media' ? form.output_modalities : [],
    protocol: form.kind === 'media' ? form.protocol : null,
    generation_kind: form.kind === 'media' ? form.generation_kind : 'create',
    audio_generation_kind: form.kind === 'media' ? form.audio_generation_kind : 'voice',
    max_concurrency: Number(form.max_concurrency),
    timeout_ms: Number(form.timeout_ms),
    enabled: form.enabled,
    context_length: form.kind === 'general' ? (parseTokenCount(form.context_length) ?? 0) : 0,
    max_output_tokens: form.kind === 'general' ? (parseTokenCount(form.max_output_tokens) ?? 0) : 0,
    billing_profile: form.billing_profile,
    token_pricing:
      form.kind === 'general'
        ? {
            input_per_million_micro_usd: micros(form.input_per_million),
            output_per_million_micro_usd: micros(form.output_per_million),
            cached_input_per_million_micro_usd: micros(form.cached_input_per_million),
          }
        : {
            input_per_million_micro_usd: 0,
            output_per_million_micro_usd: 0,
            cached_input_per_million_micro_usd: 0,
          },
    // The server drops sections the endpoint's capabilities do not cover, so
    // the form can send all four without stale prices surviving a capability
    // change.
    media_pricing:
      form.kind === 'media'
        ? {
            image: {
              input_per_image_micro_usd: micros(form.image_input),
              generation_per_image_micro_usd: micros(form.image_generation),
              generation_per_image_by_tier_micro_usd: tierPricePayload(
                form.image_generation_by_tier,
                currency,
                rateMicro,
              ),
              reference_image_free_count: Number(form.image_reference_free_count || 0),
            },
            audio: { per_10k_characters_micro_usd: micros(form.audio_per_10k) },
            music: { per_request_micro_usd: micros(form.music_per_request) },
            video: {
              generation_per_second_micro_usd: resolutionPricePayload(
                form.video_generation,
                currency,
                rateMicro,
              ),
              input_material_per_second_micro_usd: resolutionPricePayload(
                form.video_input_material,
                currency,
                rateMicro,
              ),
              reference_image_free_count: Number(form.video_reference_free_count || 0),
              extra_reference_image_micro_usd: micros(form.video_extra_reference),
            },
            token_video: {
              per_million_tokens_micro_usd: micros(form.token_video_no_ref),
              per_million_tokens_with_video_ref_micro_usd: micros(form.token_video_with_ref),
            },
          }
        : {},
  };
}

/**
 * Model management console: a flat primary/backup list of endpoints
 * (general and media), plus one shared editor dialog.
 *
 * Writes go through `PUT /admin/llm-providers/{id}`, which itself writes
 * through the versioned config centre — so every save here is still
 * audited and rollback-able like any other platform config change.
 * Timeout and concurrency are maintained on each general endpoint. The
 * gateway's bounded retry/breaker safeguards are code defaults, not another
 * global configuration panel.
 */
export function LlmProvidersPanel({
  initial,
  catalog,
}: {
  initial: LlmProviderPool;
  catalog: ModelCatalogResponse;
}) {
  const t = useTranslations('adminProviders');
  const tAdmin = useTranslations('admin');
  const tConfig = useTranslations('adminConfig');
  const { notify } = useToast();
  const { role } = useAdminSession();
  const editable = atLeast(role, 'admin');

  const [pool, setPool] = useState(initial);
  const endpoints = pool.endpoints ?? [];
  const endpointGroups = (['general', 'media'] as const).map((kind) => ({
    kind,
    endpoints: endpoints
      .filter((endpoint) => endpoint.kind === kind)
      .slice()
      .sort((a, b) =>
        kind === 'general'
          ? Number(a.role === 'backup') - Number(b.role === 'backup') ||
            a.backup_order - b.backup_order ||
            a.id.localeCompare(b.id)
          : a.id.localeCompare(b.id),
      ),
  }));

  const [editing, setEditing] = useState<EndpointFormState | null>(null);
  // Display currency for the price fields only — never sent to the API.
  // Opening the editor always starts in USD so stored micro-USD round-trips
  // exactly; CNY is an input convenience that converts on toggle and save.
  const [priceCurrency, setPriceCurrency] = useState<PriceInputCurrency>('USD');
  const [cnyPerUsd, setCnyPerUsd] = useState(DEFAULT_CNY_PER_USD);
  const [removing, setRemoving] = useState<LlmProviderEndpoint | null>(null);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [inFlight, setInFlight] = useState<Record<string, ValidationInFlight>>({});
  const [nowMs, setNowMs] = useState(() => Date.now());
  const inFlightIds = useRef(new Set<string>());
  const abortRef = useRef<AbortController | null>(null);
  const [confirmingValidation, setConfirmingValidation] = useState<LlmProviderEndpoint | null>(
    null,
  );
  const [validationResults, setValidationResults] = useState<
    Record<string, LlmProviderValidationResult>
  >({});
  const knownIds = new Set(endpoints.map((e) => e.id));

  // Created here rather than at the `useRef` initializer: Strict Mode's
  // dev-only mount -> cleanup -> remount simulation would otherwise abort
  // the one-and-only controller `useRef` ever builds before the operator
  // gets to click anything, poisoning every future validation poll for the
  // rest of the page's life. Building it fresh on every genuine effect run
  // means the simulated remount hands back a live controller instead.
  useEffect(() => {
    const controller = new AbortController();
    abortRef.current = controller;
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (Object.keys(inFlight).length === 0) return;
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [inFlight]);

  const hasPrimaryOfKind = (kind: LlmProviderKind) =>
    endpoints.some((endpoint) => endpoint.kind === kind && endpoint.role === 'primary');

  const reload = async () => {
    setPool(await adminApi.get<LlmProviderPool>('/v1/admin/llm-providers'));
  };

  const refreshList = async () => {
    setRefreshing(true);
    try {
      await reload();
    } catch (caught) {
      notify(caught instanceof ApiError ? caught.message : tAdmin('loadFailed'), 'error');
    } finally {
      setRefreshing(false);
    }
  };

  const resetPriceInput = () => {
    setPriceCurrency('USD');
    setCnyPerUsd(DEFAULT_CNY_PER_USD);
  };

  const closeEditor = () => {
    setEditing(null);
    setError(null);
    resetPriceInput();
  };

  const openCreate = () => {
    resetPriceInput();
    setEditing(emptyForm(generateModelId(knownIds), 'general', hasPrimaryOfKind('general')));
  };

  const openEdit = (endpoint: LlmProviderEndpoint) => {
    resetPriceInput();
    setEditing(formFrom(endpoint));
  };

  const changePriceCurrency = (next: PriceInputCurrency) => {
    if (!editing || next === priceCurrency) return;
    const rateMicro = parseCnyPerUsd(cnyPerUsd);
    if (rateMicro === null) {
      setError(t('fxRateInvalid'));
      return;
    }
    setError(null);
    setEditing({ ...editing, ...convertFormPrices(editing, priceCurrency, next, rateMicro) });
    setPriceCurrency(next);
  };

  const save = async () => {
    if (!editing) return;
    setBusy(true);
    setError(null);
    try {
      if (!editing.model.trim()) {
        setError(editing.kind === 'media' ? t('mediaModelRequired') : t('endpointModelHint'));
        setBusy(false);
        return;
      }
      if (
        editing.kind === 'media' &&
        capabilitiesForModalities(editing.input_modalities, editing.output_modalities).length === 0
      ) {
        setError(t('modalitiesRequired'));
        setBusy(false);
        return;
      }
      // A price that does not parse is rejected here rather than coerced to
      // zero, which would silently register the model as free and drag the
      // router's cost context toward it. CNY also needs a positive rate —
      // we never fall back to 7.2 on a typo.
      const rateMicro = priceCurrency === 'CNY' ? parseCnyPerUsd(cnyPerUsd) : 1;
      if (priceCurrency === 'CNY' && rateMicro === null) {
        setError(t('fxRateInvalid'));
        setBusy(false);
        return;
      }
      if (
        priceFields(editing).some(
          (value) => displayToMicroUsd(value, priceCurrency, rateMicro ?? 1) === null,
        )
      ) {
        setError(t('pricingInvalid'));
        setBusy(false);
        return;
      }
      if (
        editing.kind === 'general' &&
        [editing.context_length, editing.max_output_tokens].some(
          (value) => parseTokenCount(value) === null,
        )
      ) {
        setError(t('tokenCountInvalid'));
        setBusy(false);
        return;
      }
      const updated = await adminApi.put<LlmProviderPool>(
        `/v1/admin/llm-providers/${editing.id}`,
        buildUpsertPayload(editing, priceCurrency, rateMicro ?? 1),
      );
      setPool(updated);
      const demoted = updated.demoted_endpoint_ids ?? [];
      if (demoted.length > 0) {
        notify(t('demotedNotice', { count: demoted.length }), 'info');
      }
      notify(t('modelSaved'), 'success');
      closeEditor();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : tAdmin('loadFailed'));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (reason: string) => {
    if (!removing) return;
    await adminApi.post(`/v1/admin/llm-providers/${removing.id}/remove`, { reason, confirm: true });
    notify(t('modelRemoved'), 'success');
    await reload();
  };

  const toggleEnabled = async (endpoint: LlmProviderEndpoint) => {
    setTogglingId(endpoint.id);
    try {
      const payload = buildUpsertPayload({ ...formFrom(endpoint), enabled: !endpoint.enabled });
      const updated = await adminApi.put<LlmProviderPool>(
        `/v1/admin/llm-providers/${endpoint.id}`,
        payload,
      );
      setPool(updated);
      notify(endpoint.enabled ? t('modelDisabled') : t('modelEnabledNotice'), 'success');
    } catch (caught) {
      notify(caught instanceof ApiError ? caught.message : tAdmin('loadFailed'), 'error');
    } finally {
      setTogglingId(null);
    }
  };

  const validateEndpoint = async (endpoint: LlmProviderEndpoint) => {
    if (inFlightIds.current.has(endpoint.id)) return;
    // Read once and reuse for the whole call: the mount effect above is the
    // only thing that ever replaces `abortRef.current`, and it does so
    // before this handler can run, so `null` here would only mean the
    // component never actually mounted.
    const controller = abortRef.current;
    if (!controller) return;
    inFlightIds.current.add(endpoint.id);
    const startedAt = Date.now();
    setNowMs(startedAt);
    setInFlight((current) => ({
      ...current,
      [endpoint.id]: {
        validationId: '',
        startedAt,
        timeoutMs: endpoint.timeout_ms,
      },
    }));
    try {
      const job = await adminApi.post<LlmProviderValidationJob>(
        `/v1/admin/llm-providers/${endpoint.id}/validate`,
      );
      setInFlight((current) => ({
        ...current,
        [endpoint.id]: {
          validationId: job.validation_id,
          startedAt,
          timeoutMs: job.timeout_ms,
        },
      }));
      const deadline = Date.now() + job.timeout_ms + 15_000;
      while (Date.now() < deadline) {
        const latest = await adminApi.get<LlmProviderValidationJob>(
          `/v1/admin/llm-providers/${endpoint.id}/validate/${job.validation_id}`,
          { signal: controller.signal },
        );
        if (latest.status === 'completed' && latest.result) {
          setValidationResults((current) => ({ ...current, [endpoint.id]: latest.result! }));
          notify(
            latest.result.usable ? t('validationSucceeded') : t('validationFailed'),
            latest.result.usable ? 'success' : 'error',
          );
          return;
        }
        await delay(1000, controller.signal);
      }
      notify(t('validationErrorTimeout'), 'error');
    } catch (caught) {
      if (isAbortError(caught) || controller.signal.aborted) return;
      notify(caught instanceof ApiError ? caught.message : tAdmin('loadFailed'), 'error');
    } finally {
      inFlightIds.current.delete(endpoint.id);
      setInFlight((current) => {
        const next = { ...current };
        delete next[endpoint.id];
        return next;
      });
    }
  };

  const requestValidation = (endpoint: LlmProviderEndpoint) => {
    if (endpoint.kind === 'media') {
      setConfirmingValidation(endpoint);
      return;
    }
    void validateEndpoint(endpoint);
  };

  return (
    <section className="flex flex-col gap-4">
      <div className="flex justify-end gap-2">
        <Button
          size="sm"
          variant="secondary"
          icon={<IconRefresh />}
          loading={refreshing}
          onClick={() => void refreshList()}
        >
          {tAdmin('refresh')}
        </Button>
        {editable ? (
          <Button size="sm" onClick={openCreate}>
            {t('addProvider')}
          </Button>
        ) : null}
      </div>

      {endpoints.length === 0 ? (
        <EmptyState title={t('listEmpty')} description={t('listEmptyDesc')} />
      ) : (
        endpointGroups.map((group) => (
          <div
            key={group.kind}
            className="rounded-[var(--radius-md)] border border-border bg-surface p-5"
          >
            <h3 className="mb-3 text-sm font-semibold">
              {group.kind === 'general' ? t('modelTypeGeneral') : t('modelTypeMedia')}
            </h3>
            <div className="flex flex-col gap-2">
              {group.endpoints.map((endpoint) => {
                const flight = inFlight[endpoint.id];
                return (
                  <NodeRow
                    key={endpoint.id}
                    endpoint={endpoint}
                    editable={editable}
                    toggling={togglingId === endpoint.id}
                    validating={flight != null}
                    validatingElapsedMs={flight ? Math.max(0, nowMs - flight.startedAt) : 0}
                    validatingTimeoutMs={flight?.timeoutMs ?? endpoint.timeout_ms}
                    validationResult={flight ? undefined : validationResults[endpoint.id]}
                    onEdit={openEdit}
                    onRemove={(item) => setRemoving(item)}
                    onToggleEnabled={toggleEnabled}
                    onValidate={requestValidation}
                  />
                );
              })}
            </div>
          </div>
        ))
      )}

      <Dialog
        open={editing !== null}
        onClose={closeEditor}
        size="lg"
        title={editing?.id && knownIds.has(editing.id) ? t('editModel') : t('addModel')}
        footer={
          <Button loading={busy} onClick={() => void save()}>
            {tAdmin('save')}
          </Button>
        }
      >
        {editing ? (
          <div className="flex flex-col gap-3">
            <TextInput
              layout="inline"
              label={t('modelName')}
              value={editing.name}
              onChange={(event) =>
                setEditing((current) => current && { ...current, name: event.target.value })
              }
            />
            <TextInput
              layout="inline"
              label={t('baseUrl')}
              hint={editing.kind === 'media' ? t('baseUrlMediaHint') : undefined}
              value={editing.base_url}
              onChange={(event) =>
                setEditing((current) => current && { ...current, base_url: event.target.value })
              }
            />
            <TextInput
              layout="inline"
              label={t('apiKey')}
              type="password"
              placeholder={t('apiKeyPlaceholder')}
              hint={tConfig('secretMasked')}
              value={editing.api_key}
              onChange={(event) =>
                setEditing((current) => current && { ...current, api_key: event.target.value })
              }
            />
            <Select
              layout="inline"
              label={t('modelType')}
              value={editing.kind}
              options={[
                { value: 'general', label: t('modelTypeGeneral') },
                { value: 'media', label: t('modelTypeMedia') },
              ]}
              onChange={(event) =>
                setEditing((current) => {
                  if (!current) return current;
                  const kind = event.target.value as LlmProviderKind;
                  return {
                    ...current,
                    kind,
                    // The known-model catalogue is kind-scoped (a "media"
                    // preset makes no sense once the kind flips to
                    // "general", and vice versa) — back to free text.
                    vendor: CUSTOM_VENDOR,
                    billing_profile: null,
                    protocol: kind === 'media' ? current.protocol || 'openai' : current.protocol,
                    generation_kind: kind === 'media' ? current.generation_kind : 'create',
                    audio_generation_kind:
                      kind === 'media' ? current.audio_generation_kind : 'voice',
                    role: hasPrimaryOfKind(kind) ? current.role : 'primary',
                  };
                })
              }
            />

            <VendorModelPicker
              catalog={catalog}
              editing={editing}
              priceCurrency={priceCurrency}
              cnyPerUsd={cnyPerUsd}
              onChange={(patch) => setEditing((current) => current && { ...current, ...patch })}
            />

            <TextInput
              layout="inline"
              label={editing.kind === 'general' ? t('endpointModel') : t('mediaModelName')}
              hint={editing.kind === 'general' ? t('endpointModelHint') : t('mediaModelNameHint')}
              value={editing.model}
              onChange={(event) =>
                setEditing((current) => current && { ...current, model: event.target.value })
              }
            />

            {editing.kind === 'media' ? (
              <>
                <Select
                  layout="inline"
                  label={t('mediaProtocol')}
                  hint={t('mediaProtocolHint')}
                  value={editing.protocol}
                  options={MEDIA_PROTOCOLS.map((protocol) => ({
                    value: protocol,
                    label: t(PROTOCOL_LABEL_KEYS[protocol]),
                    disabled: !IMPLEMENTED_MEDIA_PROTOCOLS.has(protocol),
                  }))}
                  onChange={(event) => {
                    const protocol = event.target.value as MediaProtocol;
                    setEditing(
                      (current) =>
                        current && {
                          ...current,
                          protocol,
                          ...constrainModalities(
                            protocol,
                            current.input_modalities,
                            current.output_modalities,
                          ),
                        },
                    );
                  }}
                />
                <Select
                  layout="inline"
                  label={t('generationKind')}
                  hint={t('generationKindHint')}
                  value={editing.generation_kind}
                  options={[
                    { value: 'create', label: t('generationKindCreate') },
                    { value: 'edit', label: t('generationKindEdit') },
                  ]}
                  onChange={(event) =>
                    setEditing(
                      (current) =>
                        current && {
                          ...current,
                          generation_kind: event.target.value === 'edit' ? 'edit' : 'create',
                        },
                    )
                  }
                />
                <ModalitySelector
                  inputModalities={editing.input_modalities}
                  outputModalities={editing.output_modalities}
                  audioGenerationKind={editing.audio_generation_kind}
                  onChange={(next) => setEditing((current) => current && { ...current, ...next })}
                  onAudioGenerationKindChange={(audio_generation_kind) =>
                    setEditing((current) => current && { ...current, audio_generation_kind })
                  }
                />
              </>
            ) : null}

            {editing.kind === 'general' ? (
              <>
                <GeneralModalitySelector
                  inputModalities={editing.input_modalities as GeneralInputModality[]}
                  onChange={(next) =>
                    setEditing((current) => current && { ...current, input_modalities: next })
                  }
                />
                <Select
                  layout="inline"
                  label={t('nodeRole')}
                  value={editing.role}
                  hint={editing.role === 'primary' ? t('setPrimaryHint') : undefined}
                  options={[
                    { value: 'primary', label: t('rolePrimary') },
                    { value: 'backup', label: t('roleBackup') },
                  ]}
                  onChange={(event) =>
                    setEditing(
                      (current) =>
                        current && { ...current, role: event.target.value as 'primary' | 'backup' },
                    )
                  }
                />
                <TextInput
                  layout="inline"
                  label={t('backupOrder')}
                  hint={t('backupOrderHint')}
                  type="number"
                  min="1"
                  disabled={editing.role === 'primary'}
                  value={editing.backup_order}
                  onChange={(event) =>
                    setEditing(
                      (current) => current && { ...current, backup_order: event.target.value },
                    )
                  }
                />
                <TextInput
                  layout="inline"
                  label={t('maxConcurrency')}
                  type="number"
                  min="1"
                  value={editing.max_concurrency}
                  onChange={(event) =>
                    setEditing(
                      (current) => current && { ...current, max_concurrency: event.target.value },
                    )
                  }
                />
              </>
            ) : null}
            <div>
              <TextInput
                layout="inline"
                label={t('timeoutMs')}
                type="number"
                min="1000"
                max="600000"
                value={editing.timeout_ms}
                onChange={(event) =>
                  setEditing((current) => current && { ...current, timeout_ms: event.target.value })
                }
              />
            </div>

            <PricingFields
              form={editing}
              currency={priceCurrency}
              cnyPerUsd={cnyPerUsd}
              selectedCatalogEntry={findCatalogEntry(catalog, editing.vendor, editing.model)}
              onChange={(patch) => setEditing((current) => current && { ...current, ...patch })}
              onCurrencyChange={changePriceCurrency}
              onRateChange={setCnyPerUsd}
            />

            {error ? <ErrorNotice title={error} /> : null}
          </div>
        ) : null}
      </Dialog>

      <Dialog
        open={confirmingValidation !== null}
        onClose={() => setConfirmingValidation(null)}
        title={t('validateMediaTitle')}
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setConfirmingValidation(null)}>
              {t('cancelValidation')}
            </Button>
            <Button
              onClick={() => {
                const endpoint = confirmingValidation;
                setConfirmingValidation(null);
                if (endpoint) void validateEndpoint(endpoint);
              }}
            >
              {t('confirmValidation')}
            </Button>
          </div>
        }
      >
        <p className="text-sm leading-relaxed text-muted">{t('validateMediaDescription')}</p>
      </Dialog>

      <DangerConfirm
        open={removing !== null}
        onClose={() => setRemoving(null)}
        title={t('removeModel')}
        description={t('removeModelDesc')}
        reasonLabel={tAdmin('dangerReason')}
        onConfirm={remove}
      />
    </section>
  );
}

/**
 * The price block, which follows the endpoint's declared output modalities
 * rather than showing all four vendor price shapes at once: an image endpoint
 * has no per-second video rate to fill in, and offering the field invites a
 * price that the server would drop on save anyway.
 *
 * Everything is entered per the vendor's own quoted unit — per million
 * tokens, per image, per 10K characters, per second of video — in the
 * display currency the operator selected, and converted to micro-USD on
 * save. CNY uses the form-local rate, never a stored config value.
 */
/**
 * "Service provider -> known model" picker: purely a preset-filling
 * convenience layered on top of the always-editable free-text fields below
 * it. Picking a vendor other than "custom" narrows the model dropdown to
 * that vendor's catalogue (`app.providers.model_catalog`); picking a known
 * model there copies its real base URL / protocol / modalities onto the
 * form, which the operator can still hand-edit afterwards — nothing here
 * is sent to the API or enforced at save time (see `ModelCatalogEntryView`
 * on the backend).
 */
/**
 * Turns one known model's `price_items` into the same structured pricing
 * fields `PricingFields` renders — the mapping is the vocabulary shared
 * between `app.providers.model_catalog.PriceItem.key` and this form.
 * Written in the operator's current display currency/rate so applying a
 * preset never needs to silently flip the currency selector back to USD
 * underneath them.
 */
function priceItemsToFormPatch(
  items: PriceItem[],
  currency: PriceInputCurrency,
  rateMicro: number,
): Partial<EndpointFormState> {
  const toDisplay = (micro: number) => microUsdToDisplay(micro, currency, rateMicro);
  const patch: Partial<EndpointFormState> = {};
  const videoGeneration: Record<string, string> = {};
  const videoInputMaterial: Record<string, string> = {};
  const imageGenerationByTier: Record<string, string> = {};
  for (const item of items) {
    const display = toDisplay(item.default_micro_usd);
    switch (item.key) {
      case 'video_generation':
        if (item.dimension) videoGeneration[item.dimension] = display;
        break;
      case 'video_input_material':
        if (item.dimension) videoInputMaterial[item.dimension] = display;
        break;
      case 'video_extra_reference_image':
        patch.video_extra_reference = display;
        if (item.free_count != null) patch.video_reference_free_count = String(item.free_count);
        break;
      case 'image_generation':
        if (item.dimension) imageGenerationByTier[item.dimension] = display;
        else patch.image_generation = display;
        break;
      case 'image_input_reference':
        patch.image_input = display;
        if (item.free_count != null) patch.image_reference_free_count = String(item.free_count);
        break;
      case 'token_video_no_ref':
        patch.token_video_no_ref = display;
        break;
      case 'token_video_with_ref':
        patch.token_video_with_ref = display;
        break;
      case 'llm_input_tokens':
        patch.input_per_million = display;
        break;
      case 'llm_output_tokens':
        patch.output_per_million = display;
        break;
      case 'llm_cached_input_tokens':
        patch.cached_input_per_million = display;
        break;
      case 'audio_generation':
        // Only the per-character TTS shape maps onto this form's one audio
        // field today — a per-request item (e.g. fal's voice-clone, billed
        // per call, not per character) has no home yet, so it is left for
        // the audio-studio pricing UI to grow a field for instead of
        // silently mislabelling its dollar amount as "per 10k characters".
        if (item.unit === 'per_10k_characters') patch.audio_per_10k = display;
        break;
      default:
        break;
    }
  }
  if (Object.keys(videoGeneration).length > 0) {
    patch.video_generation = { ...emptyResolutionPrices(), ...videoGeneration };
  }
  if (Object.keys(videoInputMaterial).length > 0) {
    patch.video_input_material = { ...emptyResolutionPrices(), ...videoInputMaterial };
  }
  if (Object.keys(imageGenerationByTier).length > 0) {
    patch.image_generation_by_tier = { ...emptyTierPrices(), ...imageGenerationByTier };
  }
  return patch;
}

function VendorModelPicker({
  catalog,
  editing,
  priceCurrency,
  cnyPerUsd,
  onChange,
}: {
  catalog: ModelCatalogResponse;
  editing: EndpointFormState;
  priceCurrency: PriceInputCurrency;
  cnyPerUsd: string;
  onChange: (patch: Partial<EndpointFormState>) => void;
}) {
  const t = useTranslations('adminProviders');
  const vendors = catalog.vendors ?? [];
  const activeVendor = vendors.find((item) => item.vendor === editing.vendor);
  const knownModels = (activeVendor?.models ?? []).filter((entry) => entry.kind === editing.kind);
  const selectedEntry = knownModels.find((entry) => entry.model === editing.model);

  const applyVendor = (vendor: VendorChoice) => {
    const next = vendors.find((item) => item.vendor === vendor);
    onChange({
      vendor,
      base_url: !editing.base_url.trim() && next ? next.base_url : editing.base_url,
    });
  };

  const applyModel = (modelId: string) => {
    const entry = knownModels.find((item) => item.model === modelId);
    if (!entry) return;
    const rateMicro = priceCurrency === 'CNY' ? parseCnyPerUsd(cnyPerUsd) ?? 1 : 1;
    const pricingPatch = priceItemsToFormPatch(entry.price_items ?? [], priceCurrency, rateMicro);
    if (editing.kind === 'media') {
      onChange({
        model: entry.model,
        base_url: activeVendor?.base_url ?? editing.base_url,
        protocol: (entry.protocol as MediaProtocol | null) ?? editing.protocol,
        generation_kind: entry.generation_kind === 'edit' ? 'edit' : 'create',
        input_modalities: entry.input_modalities as MediaInputModality[],
        output_modalities: entry.output_modalities as MediaOutputModality[],
        billing_profile: entry.billing_profile ?? null,
        ...(entry.suggested_timeout_ms > 0
          ? { timeout_ms: String(entry.suggested_timeout_ms) }
          : {}),
        ...pricingPatch,
      });
      return;
    }
    onChange({
      model: entry.model,
      base_url: activeVendor?.base_url ?? editing.base_url,
      context_length: entry.context_length ? formatTokenCount(entry.context_length) : editing.context_length,
      billing_profile: entry.billing_profile ?? null,
      ...pricingPatch,
    });
  };

  return (
    <div className="flex flex-col gap-3 rounded-[var(--radius-sm)] border border-border p-3">
      <Select
        layout="inline"
        label={t('serviceProvider')}
        hint={t('serviceProviderHint')}
        value={editing.vendor}
        options={[
          { value: CUSTOM_VENDOR, label: t('serviceProviderCustom') },
          ...vendors.map((item) => ({ value: item.vendor, label: item.label })),
        ]}
        onChange={(event) => applyVendor(event.target.value as VendorChoice)}
      />
      {editing.vendor !== CUSTOM_VENDOR ? (
        knownModels.length > 0 ? (
          <>
            <Select
              layout="inline"
              label={t('knownModel')}
              hint={t('knownModelHint')}
              value={selectedEntry ? selectedEntry.model : ''}
              options={[
                { value: '', label: t('knownModelCustomOption') },
                ...knownModels.map((entry) => ({ value: entry.model, label: entry.display_name })),
              ]}
              onChange={(event) => applyModel(event.target.value)}
            />
            {selectedEntry?.notes ? (
              <p className="text-xs leading-relaxed text-muted">{selectedEntry.notes}</p>
            ) : null}
          </>
        ) : (
          <p className="text-xs text-muted">{t('knownModelEmpty')}</p>
        )
      ) : null}
    </div>
  );
}

function PricingFields({
  form,
  currency,
  cnyPerUsd,
  selectedCatalogEntry,
  onChange,
  onCurrencyChange,
  onRateChange,
}: {
  form: EndpointFormState;
  currency: PriceInputCurrency;
  cnyPerUsd: string;
  // The catalog entry for the currently selected known model, or `undefined`
  // for a custom/hand-typed one (or none selected yet). Narrows which
  // resolution/tier keys and which of the per-second vs. per-token video
  // sections actually apply — see `relevantDimensions`.
  selectedCatalogEntry?: ModelCatalogEntry;
  onChange: (patch: Partial<EndpointFormState>) => void;
  onCurrencyChange: (currency: PriceInputCurrency) => void;
  onRateChange: (value: string) => void;
}) {
  const t = useTranslations('adminProviders');
  const outputs = new Set(form.output_modalities);
  const currencyLabel = currency === 'USD' ? t('pricingCurrencyUsd') : t('pricingCurrencyCny');
  const rateInvalid = currency === 'CNY' && parseCnyPerUsd(cnyPerUsd) === null;

  const isSeedanceTokenBilled =
    selectedCatalogEntry?.billing_profile === SEEDANCE_TOKENS_BILLING_PROFILE;
  // `undefined` (custom/unknown model) shows both video sections and every
  // resolution/tier key, same as before this filtering existed — only a
  // known catalog entry narrows anything.
  const showPerSecondVideo = selectedCatalogEntry ? !isSeedanceTokenBilled : true;
  const showTokenVideo = selectedCatalogEntry ? isSeedanceTokenBilled : true;
  const relevantResolutions = relevantDimensions(selectedCatalogEntry, [
    'video_generation',
    'video_input_material',
  ]);
  const relevantImageTiers = relevantDimensions(selectedCatalogEntry, ['image_generation']);
  // A resolution/tier the catalog does not name for this model is still
  // shown once it already carries a value — reopening the form (or the
  // operator having picked a different model earlier) must never make an
  // already-typed price disappear.
  const showResolution = (resolution: string) =>
    !relevantResolutions ||
    relevantResolutions.has(resolution) ||
    Boolean(form.video_generation[resolution]) ||
    Boolean(form.video_input_material[resolution]);
  const showImageTier = (tier: string) =>
    !relevantImageTiers ||
    relevantImageTiers.has(tier) ||
    Boolean(form.image_generation_by_tier[tier]);

  const currencyControls = (
    <>
      <Select
        layout="inline"
        label={t('pricingCurrency')}
        value={currency}
        options={[
          { value: 'USD', label: t('pricingCurrencyUsd') },
          { value: 'CNY', label: t('pricingCurrencyCny') },
        ]}
        onChange={(event) => onCurrencyChange(event.target.value as PriceInputCurrency)}
      />
      {currency === 'CNY' ? (
        <TextInput
          layout="inline"
          label={t('pricingFxRate')}
          hint={rateInvalid ? t('fxRateInvalid') : t('pricingFxRateHint')}
          inputMode="decimal"
          placeholder={DEFAULT_CNY_PER_USD}
          value={cnyPerUsd}
          onChange={(event) => onRateChange(event.target.value)}
        />
      ) : null}
    </>
  );

  if (form.kind === 'general') {
    return (
      <PricingSection title={t('pricingGeneralTitle')} hint={t('pricingGeneralHint')}>
        {currencyControls}
        <TokenCountInput
          label={t('contextLength')}
          hint={t('contextLengthHint')}
          value={form.context_length}
          onChange={(value) => onChange({ context_length: value })}
        />
        <TokenCountInput
          label={t('maxOutputTokens')}
          hint={t('maxOutputTokensHint')}
          value={form.max_output_tokens}
          onChange={(value) => onChange({ max_output_tokens: value })}
        />
        <PriceInput
          label={t('priceInputTokens')}
          hint={t('pricePerMillionHint', { currency: currencyLabel })}
          value={form.input_per_million}
          onChange={(value) => onChange({ input_per_million: value })}
        />
        <PriceInput
          label={t('priceOutputTokens')}
          hint={t('pricePerMillionHint', { currency: currencyLabel })}
          value={form.output_per_million}
          onChange={(value) => onChange({ output_per_million: value })}
        />
        <PriceInput
          label={t('priceCachedInputTokens')}
          hint={t('priceCachedInputTokensHint', { currency: currencyLabel })}
          value={form.cached_input_per_million}
          onChange={(value) => onChange({ cached_input_per_million: value })}
        />
      </PricingSection>
    );
  }

  if (outputs.size === 0) {
    return (
      <PricingSection title={t('pricingMediaTitle')} hint={t('pricingNeedsModalities')}>
        {currencyControls}
      </PricingSection>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-3 rounded-[var(--radius-sm)] border border-border p-3">
        {currencyControls}
      </div>
      {outputs.has('image') ? (
        <PricingSection title={t('pricingImageTitle')} hint={t('pricingImageHint')}>
          <TextInput
            layout="inline"
            label={t('imageFreeReferenceCount')}
            hint={t('imageFreeReferenceCountHint')}
            type="number"
            min="0"
            max="100"
            value={form.image_reference_free_count}
            onChange={(event) => onChange({ image_reference_free_count: event.target.value })}
          />
          <PriceInput
            label={t('priceImageInput')}
            hint={t('pricePerImageHint', { currency: currencyLabel })}
            value={form.image_input}
            onChange={(value) => onChange({ image_input: value })}
          />
          <PriceInput
            label={t('priceImageGeneration')}
            hint={t('priceImageGenerationFlatHint', { currency: currencyLabel })}
            value={form.image_generation}
            onChange={(value) => onChange({ image_generation: value })}
          />
          {IMAGE_TIERS.filter(showImageTier).map((tier) => (
            <PriceInput
              key={`image-tier-${tier}`}
              label={t('priceImageGenerationTier', { tier })}
              hint={t('pricePerImageHint', { currency: currencyLabel })}
              value={form.image_generation_by_tier[tier] ?? ''}
              onChange={(value) =>
                onChange({
                  image_generation_by_tier: { ...form.image_generation_by_tier, [tier]: value },
                })
              }
            />
          ))}
        </PricingSection>
      ) : null}

      {outputs.has('audio') && form.audio_generation_kind !== 'music' ? (
        <PricingSection title={t('pricingAudioTitle')} hint={t('pricingAudioHint')}>
          <PriceInput
            label={t('priceAudio')}
            hint={t('pricePer10kCharactersHint', { currency: currencyLabel })}
            value={form.audio_per_10k}
            onChange={(value) => onChange({ audio_per_10k: value })}
          />
        </PricingSection>
      ) : null}

      {outputs.has('audio') && form.audio_generation_kind === 'music' ? (
        <PricingSection title={t('pricingMusicTitle')} hint={t('pricingMusicHint')}>
          <PriceInput
            label={t('priceMusic')}
            hint={t('pricePerRequestHint', { currency: currencyLabel })}
            value={form.music_per_request}
            onChange={(value) => onChange({ music_per_request: value })}
          />
        </PricingSection>
      ) : null}

      {outputs.has('video') && showPerSecondVideo ? (
        <PricingSection title={t('pricingVideoTitle')} hint={t('pricingVideoHint')}>
          {VIDEO_RESOLUTIONS.filter(showResolution).map((resolution) => (
            <PriceInput
              key={`gen-${resolution}`}
              label={t('priceVideoGeneration', { resolution })}
              hint={t('pricePerSecondHint', { currency: currencyLabel })}
              value={form.video_generation[resolution] ?? ''}
              onChange={(value) =>
                onChange({ video_generation: { ...form.video_generation, [resolution]: value } })
              }
            />
          ))}
          {VIDEO_RESOLUTIONS.filter(showResolution).map((resolution) => (
            <PriceInput
              key={`input-${resolution}`}
              label={t('priceVideoInputMaterial', { resolution })}
              hint={t('pricePerSecondHint', { currency: currencyLabel })}
              value={form.video_input_material[resolution] ?? ''}
              onChange={(value) =>
                onChange({
                  video_input_material: { ...form.video_input_material, [resolution]: value },
                })
              }
            />
          ))}
          <TextInput
            layout="inline"
            label={t('videoFreeReferenceImages')}
            hint={t('videoFreeReferenceImagesHint')}
            type="number"
            min="0"
            max="100"
            value={form.video_reference_free_count}
            onChange={(event) => onChange({ video_reference_free_count: event.target.value })}
          />
          <PriceInput
            label={t('priceVideoExtraReferenceImage')}
            hint={t('pricePerImageHint', { currency: currencyLabel })}
            value={form.video_extra_reference}
            onChange={(value) => onChange({ video_extra_reference: value })}
          />
        </PricingSection>
      ) : null}

      {outputs.has('video') && showTokenVideo ? (
        <PricingSection title={t('pricingVideoTokenTitle')} hint={t('pricingVideoTokenHint')}>
          <PriceInput
            label={t('priceVideoTokenNoRef')}
            hint={t('pricePerMillionHint', { currency: currencyLabel })}
            value={form.token_video_no_ref}
            onChange={(value) => onChange({ token_video_no_ref: value })}
          />
          <PriceInput
            label={t('priceVideoTokenWithRef')}
            hint={t('pricePerMillionHint', { currency: currencyLabel })}
            value={form.token_video_with_ref}
            onChange={(value) => onChange({ token_video_with_ref: value })}
          />
        </PricingSection>
      ) : null}
    </div>
  );
}

function PricingSection({
  title,
  hint,
  children,
}: {
  title: string;
  hint: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 rounded-[var(--radius-sm)] border border-border p-3">
      <div>
        <p className="text-xs font-semibold">{title}</p>
        <p className="mt-1 text-xs leading-relaxed text-muted">{hint}</p>
      </div>
      {children}
    </div>
  );
}

/** A unit price in the current display currency. Free text rather than
 * `type="number"`, because a spinner on a six-decimal price is useless and
 * browsers localise the decimal separator on numeric inputs. */
function PriceInput({
  label,
  hint,
  value,
  onChange,
}: {
  label: string;
  hint: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const t = useTranslations('adminProviders');
  // Format only — a valid yuan string must not flip to "price invalid" just
  // because the rate field above it is empty. Rate errors live on the rate
  // control and on save.
  const invalid = value.trim() !== '' && dollarsToMicroUsd(value) === null;
  return (
    <TextInput
      layout="inline"
      label={label}
      hint={invalid ? t('pricingInvalid') : hint}
      inputMode="decimal"
      placeholder="0.00"
      value={value}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

/** A token count that accepts `k`/`m` shorthand (`"128k"`, `"1.5M"`) as typed
 * rather than expanding it immediately — the operator keeps editing the
 * abbreviation they wrote, and it is only converted to a plain integer on
 * save (see `buildUpsertPayload`). */
function TokenCountInput({
  label,
  hint,
  value,
  onChange,
}: {
  label: string;
  hint: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const t = useTranslations('adminProviders');
  const invalid = value.trim() !== '' && parseTokenCount(value) === null;
  return (
    <TextInput
      layout="inline"
      label={label}
      hint={invalid ? t('tokenCountInvalid') : hint}
      inputMode="text"
      placeholder="128K"
      value={value}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

/** Two modality checklists (input/output) plus a live preview of the
 * capability tags they derive, mirroring `capabilities_for_modalities` in
 * `app/platform_config/schemas.py` so what the admin sees here matches what
 * gets saved. */
function ModalitySelector({
  inputModalities,
  outputModalities,
  audioGenerationKind,
  onChange,
  onAudioGenerationKindChange,
}: {
  inputModalities: MediaInputModality[];
  outputModalities: MediaOutputModality[];
  audioGenerationKind: AudioGenerationKindValue;
  onChange: (next: {
    input_modalities: MediaInputModality[];
    output_modalities: MediaOutputModality[];
  }) => void;
  onAudioGenerationKindChange: (kind: AudioGenerationKindValue) => void;
}) {
  const t = useTranslations('adminProviders');
  // Both `audio_generation` and `music_generation` derive from the same raw
  // `text -> audio` pair (see `OPERATION_MODALITY_MAP`) — this is exactly
  // when the tie-break toggle below actually matters to the operator.
  const isAudioPairAmbiguous =
    inputModalities.includes('text') && outputModalities.includes('audio');
  const derived = capabilitiesForModalities(
    inputModalities,
    outputModalities,
    audioGenerationKind,
  );

  const toggleInput = (modality: MediaInputModality) => {
    const next = inputModalities.includes(modality)
      ? inputModalities.filter((item) => item !== modality)
      : [...inputModalities, modality];
    onChange({ input_modalities: next, output_modalities: outputModalities });
  };

  const toggleOutput = (modality: MediaOutputModality) => {
    const next = outputModalities.includes(modality)
      ? outputModalities.filter((item) => item !== modality)
      : [...outputModalities, modality];
    onChange({ input_modalities: inputModalities, output_modalities: next });
  };

  return (
    <div className="flex flex-col gap-3 rounded-[var(--radius-sm)] border border-border p-3">
      <p className="text-xs leading-relaxed text-muted">{t('modalitiesHint')}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <ModalityGroup
          title={t('inputModalities')}
          options={MEDIA_INPUT_MODALITIES}
          selected={inputModalities}
          onToggle={toggleInput}
        />
        <ModalityGroup
          title={t('outputModalities')}
          options={MEDIA_OUTPUT_MODALITIES}
          selected={outputModalities}
          onToggle={toggleOutput}
        />
      </div>
      {isAudioPairAmbiguous ? (
        <Select
          layout="inline"
          label={t('audioGenerationKind')}
          hint={t('audioGenerationKindHint')}
          value={audioGenerationKind}
          options={AUDIO_GENERATION_KINDS.map((kind) => ({
            value: kind,
            label: t(AUDIO_GENERATION_KIND_LABEL_KEYS[kind]),
          }))}
          onChange={(event) =>
            onAudioGenerationKindChange(event.target.value as AudioGenerationKindValue)
          }
        />
      ) : null}
      <div>
        <p className="text-xs font-medium text-muted">{t('derivedCapabilitiesLabel')}</p>
        {derived.length === 0 ? (
          <p className="mt-1 text-xs text-muted">{t('derivedCapabilitiesEmpty')}</p>
        ) : (
          <div className="mt-1 flex flex-wrap gap-1">
            {derived.map((tag) => (
              <Badge key={tag} tone="neutral">
                {t(OPERATION_LABEL_KEYS[tag])}
              </Badge>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/** Input-only modality picker for `kind="general"` endpoints: "text" is
 * always on (a chat endpoint always reads text) and locked, "image" is a
 * declarative label only, "video" additionally makes the endpoint a
 * `video_analysis` candidate — surfaced here so the admin sees the direct
 * effect of the toggle. Deliberately not `ModalitySelector`: that component's
 * two-column input/output grid and "derived generation capabilities" preview
 * are media-endpoint concepts that don't apply here. */
function GeneralModalitySelector({
  inputModalities,
  onChange,
}: {
  inputModalities: GeneralInputModality[];
  onChange: (next: GeneralInputModality[]) => void;
}) {
  const t = useTranslations('adminProviders');
  const supportsVideo = inputModalities.includes('video');

  const toggle = (modality: GeneralInputModality) => {
    if (modality === 'text') return;
    const next = inputModalities.includes(modality)
      ? inputModalities.filter((item) => item !== modality)
      : [...inputModalities, modality];
    onChange(next);
  };

  return (
    <div className="flex flex-col gap-3 rounded-[var(--radius-sm)] border border-border p-3">
      <p className="text-xs leading-relaxed text-muted">{t('generalModalitiesHint')}</p>
      <div className="flex flex-col rounded-[var(--radius-sm)] border border-border">
        {GENERAL_INPUT_MODALITIES.map((modality) => {
          const label = t(MODALITY_LABEL_KEYS[modality]);
          return (
            <div
              key={modality}
              className="flex items-center justify-between gap-2 border-b border-border px-3 py-2 last:border-b-0"
            >
              <span className="text-sm text-text">{label}</span>
              <InlineToggle
                label={label}
                checked={modality === 'text' || inputModalities.includes(modality)}
                disabled={modality === 'text'}
                onChange={() => toggle(modality)}
              />
            </div>
          );
        })}
      </div>
      {supportsVideo ? (
        <div>
          <Badge tone="neutral">{t(OPERATION_LABEL_KEYS.video_analysis)}</Badge>
        </div>
      ) : null}
    </div>
  );
}

function ModalityGroup<M extends string>({
  title,
  options,
  selected,
  onToggle,
}: {
  title: string;
  options: readonly M[];
  selected: M[];
  onToggle: (option: M) => void;
}) {
  const t = useTranslations('adminProviders');

  return (
    <div className="flex flex-col gap-1.5">
      <p className="text-sm font-medium text-text">{title}</p>
      <div className="flex flex-col rounded-[var(--radius-sm)] border border-border">
        {options.map((option) => {
          const label = t(MODALITY_LABEL_KEYS[option as MediaInputModality | MediaOutputModality]);
          return (
            <div
              key={option}
              className="flex items-center justify-between gap-2 border-b border-border px-3 py-2 last:border-b-0"
            >
              <span className="text-sm text-text">{label}</span>
              <InlineToggle
                label={`${title} · ${label}`}
                checked={selected.includes(option)}
                onChange={() => onToggle(option)}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Compact switch reused for modality rows and the list's enable/disable
 * action — the shared `Switch` is a full settings row (`justify-between` +
 * `py-3`) and misaligns in both of those tighter layouts. */
function InlineToggle({
  label,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (next: boolean) => void;
}) {
  const id = useId();

  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative h-6 w-11 shrink-0 rounded-full transition-colors',
        checked ? 'bg-primary' : 'bg-track',
        disabled ? 'cursor-not-allowed opacity-60' : '',
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          'absolute top-0.5 size-5 rounded-full bg-white shadow transition-[left]',
          checked ? 'left-[22px]' : 'left-0.5',
        )}
      />
    </button>
  );
}

/**
 * The row's price line. An unpriced model is called out rather than left
 * blank, because the router treats a missing price as an estimate and the
 * operator is the only one who can turn that into a real number.
 */
function PricingSummary({ endpoint }: { endpoint: LlmProviderEndpoint }) {
  const t = useTranslations('adminProviders');
  const parts: string[] = [];

  if (endpoint.kind === 'general') {
    const tokens = endpoint.token_pricing;
    if (tokens?.input_per_million_micro_usd) {
      parts.push(
        `${t('priceInputTokens')} $${microUsdToDollars(tokens.input_per_million_micro_usd)}/M`,
      );
    }
    if (tokens?.output_per_million_micro_usd) {
      parts.push(
        `${t('priceOutputTokens')} $${microUsdToDollars(tokens.output_per_million_micro_usd)}/M`,
      );
    }
    if (tokens?.cached_input_per_million_micro_usd) {
      parts.push(
        `${t('priceCachedInputTokens')} $${microUsdToDollars(tokens.cached_input_per_million_micro_usd)}/M`,
      );
    }
    if (endpoint.context_length) {
      parts.push(`${t('contextLength')} ${endpoint.context_length.toLocaleString()}`);
    }
    if (endpoint.max_output_tokens) {
      parts.push(`${t('maxOutputTokens')} ${endpoint.max_output_tokens.toLocaleString()}`);
    }
  } else {
    const media = endpoint.media_pricing;
    if (media?.image?.generation_per_image_micro_usd) {
      parts.push(
        `${t('priceImageGeneration')} $${microUsdToDollars(media.image.generation_per_image_micro_usd)}`,
      );
    }
    if (media?.image?.input_per_image_micro_usd) {
      parts.push(
        `${t('priceImageInput')} $${microUsdToDollars(media.image.input_per_image_micro_usd)}`,
      );
    }
    for (const [tier, price] of Object.entries(
      media?.image?.generation_per_image_by_tier_micro_usd ?? {},
    )) {
      parts.push(`${t('priceImageGenerationTier', { tier })} $${microUsdToDollars(price)}`);
    }
    if (media?.audio?.per_10k_characters_micro_usd) {
      parts.push(
        `${t('priceAudio')} $${microUsdToDollars(media.audio.per_10k_characters_micro_usd)}`,
      );
    }
    for (const [resolution, price] of Object.entries(
      media?.video?.generation_per_second_micro_usd ?? {},
    )) {
      parts.push(`${t('priceVideoGeneration', { resolution })} $${microUsdToDollars(price)}/s`);
    }
    if (media?.token_video?.per_million_tokens_micro_usd) {
      parts.push(
        `${t('priceVideoTokenNoRef')} $${microUsdToDollars(media.token_video.per_million_tokens_micro_usd)}/M`,
      );
    }
    if (media?.token_video?.per_million_tokens_with_video_ref_micro_usd) {
      parts.push(
        `${t('priceVideoTokenWithRef')} $${microUsdToDollars(media.token_video.per_million_tokens_with_video_ref_micro_usd)}/M`,
      );
    }
  }

  return (
    <p className="mt-1 truncate text-[11px] text-muted" title={parts.join(' · ')}>
      {parts.length > 0 ? parts.join(' · ') : t('pricingUnset')}
    </p>
  );
}

/** A square icon-only action. The label is the accessible name and the
 * hover tooltip, so nothing is lost by dropping the visible text. */
function IconAction({
  label,
  tone = 'neutral',
  busy,
  onClick,
  children,
}: {
  label: string;
  tone?: 'neutral' | 'danger';
  busy?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-busy={busy || undefined}
      disabled={busy}
      onClick={onClick}
      className={cn(
        'inline-flex size-8 items-center justify-center rounded-[var(--radius-sm)] border border-border bg-surface transition-all duration-150 ease-out',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary',
        busy
          ? 'animate-pulse cursor-progress opacity-70'
          : 'cursor-pointer hover:-translate-y-0.5 hover:shadow-sm active:translate-y-0 active:scale-90 active:shadow-none',
        tone === 'danger'
          ? 'text-danger hover:border-danger hover:bg-danger/10 active:bg-danger/15'
          : 'text-muted hover:border-primary hover:bg-primary/10 hover:text-primary active:bg-primary/15',
      )}
    >
      {children}
    </button>
  );
}

function NodeRow({
  endpoint,
  editable,
  toggling,
  validating,
  validatingElapsedMs,
  validatingTimeoutMs,
  validationResult,
  onEdit,
  onRemove,
  onToggleEnabled,
  onValidate,
}: {
  endpoint: LlmProviderEndpoint;
  editable: boolean;
  toggling: boolean;
  validating: boolean;
  validatingElapsedMs: number;
  validatingTimeoutMs: number;
  validationResult?: LlmProviderValidationResult;
  onEdit: (endpoint: LlmProviderEndpoint) => void;
  onRemove: (endpoint: LlmProviderEndpoint) => void;
  onToggleEnabled: (endpoint: LlmProviderEndpoint) => void;
  onValidate: (endpoint: LlmProviderEndpoint) => void;
}) {
  const t = useTranslations('adminProviders');
  // A general endpoint only ever derives `video_analysis` (declared via
  // `input_modalities`), but shares the same badge row media endpoints use.
  const capabilityTags = endpoint.capabilities ?? [];
  const errorLabels: Record<string, string> = {
    no_model: t('validationErrorNoModel'),
    no_capability: t('validationErrorNoCapability'),
    timeout: t('validationErrorTimeout'),
    connection_failed: t('validationErrorConnection'),
    auth_failed: t('validationErrorAuth'),
    access_forbidden: t('validationErrorAccess'),
    endpoint_not_found: t('validationErrorEndpoint'),
    rate_limited: t('validationErrorRateLimited'),
    provider_error: t('validationErrorProvider'),
    request_rejected: t('validationErrorRejected'),
    invalid_response: t('validationErrorInvalidResponse'),
  };

  return (
    <div
      className={
        'grid gap-4 rounded-[var(--radius-sm)] border p-3 sm:p-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center ' +
        (endpoint.role === 'primary'
          ? 'border-primary/40 bg-primary/5'
          : 'border-border bg-surface-soft')
      }
    >
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          {/* The name and id are the way into the editor now — a separate
              "detail" button spent a whole slot in the action strip saying
              what clicking the row's title already says. */}
          {editable ? (
            <button
              type="button"
              onClick={() => onEdit(endpoint)}
              className="group flex min-w-0 cursor-pointer items-center gap-2 rounded-[var(--radius-sm)] -mx-1.5 -my-1 px-1.5 py-1 text-left transition-colors hover:bg-primary/10 hover:text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
              title={t('editModel')}
            >
              <span className="truncate font-medium group-hover:underline">{endpoint.name}</span>
              <span className="font-mono text-[11px] text-muted">{endpoint.id}</span>
              <IconPencil className="size-3.5 shrink-0 opacity-0 transition-opacity group-hover:opacity-100" />
            </button>
          ) : (
            <>
              <span className="font-medium text-text">{endpoint.name}</span>
              <span className="font-mono text-[11px] text-muted">{endpoint.id}</span>
            </>
          )}
          <Badge tone="neutral">
            {endpoint.kind === 'general' ? t('modelTypeGeneral') : t('modelTypeMedia')}
          </Badge>
          {endpoint.kind === 'media' && endpoint.protocol ? (
            <Badge tone="neutral">
              {PROTOCOL_LABEL_KEYS[endpoint.protocol as MediaProtocol]
                ? t(PROTOCOL_LABEL_KEYS[endpoint.protocol as MediaProtocol])
                : endpoint.protocol}
            </Badge>
          ) : null}
          {endpoint.kind === 'media' ? (
            <Badge tone="neutral">
              {endpoint.generation_kind === 'edit' ? t('generationKindEdit') : t('generationKindCreate')}
            </Badge>
          ) : null}
          <Badge tone={endpoint.enabled ? 'success' : 'neutral'}>
            {endpoint.enabled ? t('enabled') : t('disabled')}
          </Badge>
          <Badge tone={endpoint.circuit_breaker_open ? 'danger' : 'success'}>
            {endpoint.circuit_breaker_open ? t('breakerOpen') : t('breakerClosed')}
          </Badge>
        </div>
        <p className="mt-0.5 truncate font-mono text-[11px] text-muted">{endpoint.base_url}</p>
        {endpoint.model ? (
          <p className="mt-0.5 truncate font-mono text-[11px] text-muted">{endpoint.model}</p>
        ) : null}
        {capabilityTags.length > 0 ? (
          <div className="mt-1 flex flex-wrap gap-1">
            {capabilityTags.map((tag) => {
              const labelKey = operationLabelKey(tag);
              return (
                <Badge key={tag} tone="neutral">
                  {labelKey ? t(labelKey) : tag}
                </Badge>
              );
            })}
          </div>
        ) : null}
        <PricingSummary endpoint={endpoint} />
        <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-muted">
          <span>
            {t('colConcurrency')}: {endpoint.concurrency_in_use} / {endpoint.max_concurrency}
          </span>
          <span>
            {t('colSuccessRate')}:{' '}
            {endpoint.recent_success_rate == null
              ? t('noRecentAttempts')
              : `${(endpoint.recent_success_rate * 100).toFixed(1)}% (${endpoint.recent_attempts})`}
          </span>
        </div>
        {validating ? (
          <div
            className="mt-2 flex flex-wrap items-center gap-2 rounded-[var(--radius-sm)] border border-border bg-surface px-2.5 py-2 text-[11px]"
            role="status"
          >
            <Badge tone="neutral">{t('validationInProgress')}</Badge>
            <span className="text-muted">
              {t('validationElapsed', { seconds: Math.floor(validatingElapsedMs / 1000) })}
            </span>
            <span className="text-muted">
              {t('validationTimeoutHint', { seconds: Math.ceil(validatingTimeoutMs / 1000) })}
            </span>
          </div>
        ) : validationResult ? (
          <div
            className="mt-2 flex flex-wrap items-center gap-2 rounded-[var(--radius-sm)] border border-border bg-surface px-2.5 py-2 text-[11px]"
            role="status"
          >
            <Badge tone={validationResult.usable ? 'success' : 'danger'}>
              {validationResult.usable ? t('validationSucceeded') : t('validationFailed')}
            </Badge>
            {validationResult.target_model ? (
              <span className="font-mono text-muted">{validationResult.target_model}</span>
            ) : null}
            <span className="text-muted">
              {t('validationLatency', { ms: validationResult.latency_ms })}
            </span>
            {validationResult.provider_status_code ? (
              <span className="text-muted">HTTP {validationResult.provider_status_code}</span>
            ) : null}
            {validationResult.error_code ? (
              <span className="text-danger">
                {errorLabels[validationResult.error_code] ?? validationResult.error_code}
              </span>
            ) : null}
            {validationResult.provider_error_code ? (
              <span className="font-mono text-danger">{validationResult.provider_error_code}</span>
            ) : null}
            {validationResult.provider_error_message ? (
              <span className="text-danger">{validationResult.provider_error_message}</span>
            ) : null}
            {validationResult.external_task_id ? (
              <span className="font-mono text-muted">
                {t('validationTaskId', { id: validationResult.external_task_id })}
              </span>
            ) : null}
          </div>
        ) : null}
      </div>
      {editable ? (
        // Enable, validate and remove all read as one action group on a
        // single row now — keeping them stacked made the row feel taller
        // than it needed to be and separated actions an operator reaches
        // for together.
        <div className="flex w-full items-center justify-end gap-3 border-t border-border pt-3 lg:w-auto lg:border-t-0 lg:border-l lg:pt-0 lg:pl-4">
          <InlineToggle
            label={`${endpoint.name} · ${t('modelEnabled')}`}
            checked={endpoint.enabled}
            disabled={toggling}
            onChange={() => onToggleEnabled(endpoint)}
          />
          <div className="flex items-center gap-1.5">
            <IconAction
              label={t('validateModel')}
              onClick={() => onValidate(endpoint)}
              busy={validating}
            >
              <IconFlask className="size-4" />
            </IconAction>
            <IconAction label={t('removeModel')} tone="danger" onClick={() => onRemove(endpoint)}>
              <IconTrash className="size-4" />
            </IconAction>
          </div>
        </div>
      ) : null}
    </div>
  );
}

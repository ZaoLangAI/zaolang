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
import { dollarsToMicroUsd, microUsdToDollars } from '@/lib/admin/micro-usd';
import { formatTokenCount, parseTokenCount } from '@/lib/admin/token-count';
import { cn } from '@/lib/cn';
import {
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
} from '@/lib/api/admin-types';
import { ApiError } from '@/lib/api/errors';

/**
 * Prices are held as the dollar strings the operator typed, not as numbers.
 * Parsing on every keystroke would fight the caret: `"0."` is not yet a
 * number, and `microUsdToDollars(dollarsToMicroUsd("0."))` is `""`, which
 * would erase the decimal point as it was typed. Conversion happens once, on
 * save.
 */
interface EndpointFormState {
  id: string;
  name: string;
  base_url: string;
  api_key: string;
  kind: LlmProviderKind;
  // The one model id this endpoint serves, whatever its kind.
  model: string;
  input_modalities: MediaInputModality[];
  output_modalities: MediaOutputModality[];
  protocol: MediaProtocol;
  role: 'primary' | 'backup';
  backup_order: string;
  max_concurrency: string;
  timeout_ms: string;
  enabled: boolean;
  // `kind="general"` pricing and limits.
  context_length: string;
  max_output_tokens: string;
  input_per_million: string;
  output_per_million: string;
  // `kind="media"` pricing, by section.
  image_input: string;
  image_generation: string;
  audio_per_10k: string;
  video_generation: Record<string, string>;
  video_input_material: Record<string, string>;
  video_reference_free_count: string;
  video_extra_reference: string;
}

/** Mirrors `VIDEO_RESOLUTIONS` in `app/platform_config/schemas.py`; the API
 * rejects any other key, so the form offers exactly these. */
const VIDEO_RESOLUTIONS = ['2K', '768P'] as const;

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
    model: '',
    input_modalities: kind === 'general' ? ['text'] : [],
    output_modalities: [],
    protocol: 'openai',
    role: !hasPrimary ? 'primary' : 'backup',
    backup_order: '100',
    max_concurrency: '4',
    timeout_ms: kind === 'media' ? '90000' : '30000',
    enabled: true,
    context_length: '',
    max_output_tokens: '',
    input_per_million: '',
    output_per_million: '',
    image_input: '',
    image_generation: '',
    audio_per_10k: '',
    video_generation: emptyResolutionPrices(),
    video_input_material: emptyResolutionPrices(),
    video_reference_free_count: '5',
    video_extra_reference: '',
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
    model: endpoint.model ?? '',
    input_modalities: (endpoint.input_modalities ?? []) as MediaInputModality[],
    output_modalities: (endpoint.output_modalities ?? []) as MediaOutputModality[],
    protocol: endpoint.kind === 'media' && endpoint.protocol ? endpoint.protocol : 'openai',
    role: endpoint.role,
    backup_order: String(endpoint.backup_order),
    max_concurrency: String(endpoint.max_concurrency),
    timeout_ms: String(endpoint.timeout_ms),
    enabled: endpoint.enabled,
    context_length: formatTokenCount(endpoint.context_length),
    max_output_tokens: formatTokenCount(endpoint.max_output_tokens),
    input_per_million: microUsdToDollars(tokens?.input_per_million_micro_usd ?? 0),
    output_per_million: microUsdToDollars(tokens?.output_per_million_micro_usd ?? 0),
    image_input: microUsdToDollars(media?.image?.input_per_image_micro_usd ?? 0),
    image_generation: microUsdToDollars(media?.image?.generation_per_image_micro_usd ?? 0),
    audio_per_10k: microUsdToDollars(media?.audio?.per_10k_characters_micro_usd ?? 0),
    video_generation: resolutionPricesFrom(media?.video?.generation_per_second_micro_usd),
    video_input_material: resolutionPricesFrom(media?.video?.input_material_per_second_micro_usd),
    video_reference_free_count: String(media?.video?.reference_image_free_count ?? 5),
    video_extra_reference: microUsdToDollars(media?.video?.extra_reference_image_micro_usd ?? 0),
  };
}

/** Every price field on the form, so validation and payload building agree on
 * what has to parse. */
function priceFields(form: EndpointFormState): string[] {
  return form.kind === 'general'
    ? [form.input_per_million, form.output_per_million]
    : [
        form.image_input,
        form.image_generation,
        form.audio_per_10k,
        form.video_extra_reference,
        ...Object.values(form.video_generation),
        ...Object.values(form.video_input_material),
      ];
}

function resolutionPricePayload(prices: Record<string, string>): Record<string, number> {
  const payload: Record<string, number> = {};
  for (const resolution of VIDEO_RESOLUTIONS) {
    const micros = dollarsToMicroUsd(prices[resolution] ?? '');
    // Only priced resolutions are sent; a zero would claim the vendor charges
    // nothing for a resolution the operator simply has not filled in.
    if (micros) payload[resolution] = micros;
  }
  return payload;
}

/** Shared shape for `PUT /admin/llm-providers/{id}`, used both by the full
 * editor save and by the list row's quick enable/disable toggle so the two
 * never drift on what a "no-op except one field" write looks like. */
function buildUpsertPayload(form: EndpointFormState) {
  const micros = (value: string) => dollarsToMicroUsd(value) ?? 0;
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
    max_concurrency: Number(form.max_concurrency),
    timeout_ms: Number(form.timeout_ms),
    enabled: form.enabled,
    context_length: form.kind === 'general' ? (parseTokenCount(form.context_length) ?? 0) : 0,
    max_output_tokens: form.kind === 'general' ? (parseTokenCount(form.max_output_tokens) ?? 0) : 0,
    token_pricing:
      form.kind === 'general'
        ? {
            input_per_million_micro_usd: micros(form.input_per_million),
            output_per_million_micro_usd: micros(form.output_per_million),
          }
        : { input_per_million_micro_usd: 0, output_per_million_micro_usd: 0 },
    // The server drops sections the endpoint's capabilities do not cover, so
    // the form can send all three without stale prices surviving a capability
    // change.
    media_pricing:
      form.kind === 'media'
        ? {
            image: {
              input_per_image_micro_usd: micros(form.image_input),
              generation_per_image_micro_usd: micros(form.image_generation),
            },
            audio: { per_10k_characters_micro_usd: micros(form.audio_per_10k) },
            video: {
              generation_per_second_micro_usd: resolutionPricePayload(form.video_generation),
              input_material_per_second_micro_usd: resolutionPricePayload(
                form.video_input_material,
              ),
              reference_image_free_count: Number(form.video_reference_free_count || 0),
              extra_reference_image_micro_usd: micros(form.video_extra_reference),
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
export function LlmProvidersPanel({ initial }: { initial: LlmProviderPool }) {
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

  const openCreate = () => {
    setEditing(emptyForm(generateModelId(knownIds), 'general', hasPrimaryOfKind('general')));
  };

  const openEdit = (endpoint: LlmProviderEndpoint) => {
    setEditing(formFrom(endpoint));
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
      // router's cost context toward it.
      if (priceFields(editing).some((value) => dollarsToMicroUsd(value) === null)) {
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
        buildUpsertPayload(editing),
      );
      setPool(updated);
      const demoted = updated.demoted_endpoint_ids ?? [];
      if (demoted.length > 0) {
        notify(t('demotedNotice', { count: demoted.length }), 'info');
      }
      notify(t('modelSaved'), 'success');
      setEditing(null);
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
        onClose={() => setEditing(null)}
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
                    protocol: kind === 'media' ? current.protocol || 'openai' : current.protocol,
                    role: hasPrimaryOfKind(kind) ? current.role : 'primary',
                  };
                })
              }
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
                <ModalitySelector
                  inputModalities={editing.input_modalities}
                  outputModalities={editing.output_modalities}
                  onChange={(next) => setEditing((current) => current && { ...current, ...next })}
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
                max="120000"
                value={editing.timeout_ms}
                onChange={(event) =>
                  setEditing((current) => current && { ...current, timeout_ms: event.target.value })
                }
              />
            </div>

            <PricingFields
              form={editing}
              onChange={(patch) => setEditing((current) => current && { ...current, ...patch })}
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
 * Everything is entered in dollars per the vendor's own quoted unit — per
 * million tokens, per image, per 10K characters, per second of video — and
 * converted to micro-USD on save.
 */
function PricingFields({
  form,
  onChange,
}: {
  form: EndpointFormState;
  onChange: (patch: Partial<EndpointFormState>) => void;
}) {
  const t = useTranslations('adminProviders');
  const outputs = new Set(form.output_modalities);

  if (form.kind === 'general') {
    return (
      <PricingSection title={t('pricingGeneralTitle')} hint={t('pricingGeneralHint')}>
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
          hint={t('pricePerMillionHint')}
          value={form.input_per_million}
          onChange={(value) => onChange({ input_per_million: value })}
        />
        <PriceInput
          label={t('priceOutputTokens')}
          hint={t('pricePerMillionHint')}
          value={form.output_per_million}
          onChange={(value) => onChange({ output_per_million: value })}
        />
      </PricingSection>
    );
  }

  if (outputs.size === 0) {
    return (
      <PricingSection title={t('pricingMediaTitle')} hint={t('pricingNeedsModalities')}>
        {null}
      </PricingSection>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {outputs.has('image') ? (
        <PricingSection title={t('pricingImageTitle')} hint={t('pricingImageHint')}>
          <PriceInput
            label={t('priceImageInput')}
            hint={t('pricePerImageHint')}
            value={form.image_input}
            onChange={(value) => onChange({ image_input: value })}
          />
          <PriceInput
            label={t('priceImageGeneration')}
            hint={t('pricePerImageHint')}
            value={form.image_generation}
            onChange={(value) => onChange({ image_generation: value })}
          />
        </PricingSection>
      ) : null}

      {outputs.has('audio') ? (
        <PricingSection title={t('pricingAudioTitle')} hint={t('pricingAudioHint')}>
          <PriceInput
            label={t('priceAudio')}
            hint={t('pricePer10kCharactersHint')}
            value={form.audio_per_10k}
            onChange={(value) => onChange({ audio_per_10k: value })}
          />
        </PricingSection>
      ) : null}

      {outputs.has('video') ? (
        <PricingSection title={t('pricingVideoTitle')} hint={t('pricingVideoHint')}>
          {VIDEO_RESOLUTIONS.map((resolution) => (
            <PriceInput
              key={`gen-${resolution}`}
              label={t('priceVideoGeneration', { resolution })}
              hint={t('pricePerSecondHint')}
              value={form.video_generation[resolution] ?? ''}
              onChange={(value) =>
                onChange({ video_generation: { ...form.video_generation, [resolution]: value } })
              }
            />
          ))}
          {VIDEO_RESOLUTIONS.map((resolution) => (
            <PriceInput
              key={`input-${resolution}`}
              label={t('priceVideoInputMaterial', { resolution })}
              hint={t('pricePerSecondHint')}
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
            hint={t('pricePerImageHint')}
            value={form.video_extra_reference}
            onChange={(value) => onChange({ video_extra_reference: value })}
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

/** A dollar amount. Free text rather than `type="number"`, because a spinner
 * on a six-decimal price is useless and browsers localise the decimal
 * separator on numeric inputs. */
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
  onChange,
}: {
  inputModalities: MediaInputModality[];
  outputModalities: MediaOutputModality[];
  onChange: (next: {
    input_modalities: MediaInputModality[];
    output_modalities: MediaOutputModality[];
  }) => void;
}) {
  const t = useTranslations('adminProviders');
  const derived = capabilitiesForModalities(inputModalities, outputModalities);

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

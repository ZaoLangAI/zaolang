'use client';

import { useTranslations } from 'next-intl';
import { useId, useState } from 'react';

import { useAdminSession } from '@/components/admin/admin-session-provider';
import { DangerConfirm } from '@/components/admin/danger-confirm';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Select, TextInput } from '@/components/ui/field';
import { Badge, EmptyState, ErrorNotice } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { cn } from '@/lib/cn';
import { atLeast } from '@/lib/admin/rbac';
import { adminApi } from '@/lib/api/admin-client';
import type { LlmProviderEndpoint, LlmProviderKind, LlmProviderPool } from '@/lib/api/admin-types';
import { ApiError } from '@/lib/api/errors';

// Fixed set, mirroring `MEDIA_CAPABILITIES` in `app/platform_config/schemas.py`
// — the six capability tags a `kind="media"` endpoint may serve.
const MEDIA_CAPABILITY_TAGS = [
  'text_to_image',
  'image_to_image',
  'text_to_video',
  'image_to_video',
  'video_to_video',
  'audio_generation',
] as const;
type MediaCapabilityTag = (typeof MEDIA_CAPABILITY_TAGS)[number];

const CAPABILITY_LABEL_KEYS: Record<MediaCapabilityTag, string> = {
  text_to_image: 'capabilityTextToImage',
  image_to_image: 'capabilityImageToImage',
  text_to_video: 'capabilityTextToVideo',
  image_to_video: 'capabilityImageToVideo',
  video_to_video: 'capabilityVideoToVideo',
  audio_generation: 'capabilityAudioGeneration',
};

// The two modality axes an operator picks from instead of naming a capability
// tag directly, mirroring `MEDIA_INPUT_MODALITIES`/`MEDIA_OUTPUT_MODALITIES`
// in `app/platform_config/schemas.py`. `audio` is a valid input (e.g.
// voice-driven lip-sync video) even though no capability tag derives from it
// alone yet — see `CAPABILITY_MODALITY_MAP` below.
const MEDIA_INPUT_MODALITIES = ['text', 'image', 'video', 'audio'] as const;
type MediaInputModality = (typeof MEDIA_INPUT_MODALITIES)[number];
const MEDIA_OUTPUT_MODALITIES = ['image', 'video', 'audio'] as const;
type MediaOutputModality = (typeof MEDIA_OUTPUT_MODALITIES)[number];

const MODALITY_LABEL_KEYS: Record<MediaInputModality | MediaOutputModality, string> = {
  text: 'modalityText',
  image: 'modalityImage',
  video: 'modalityVideo',
  audio: 'modalityAudio',
};

// One (input, output) pair per capability tag — mirrors the backend's
// `_CAPABILITY_MODALITY_MAP`. Kept in sync by hand since this is a small,
// stable, six-entry table shared by exactly these two places.
const CAPABILITY_MODALITY_MAP: Record<MediaCapabilityTag, readonly [MediaInputModality, MediaOutputModality]> = {
  text_to_image: ['text', 'image'],
  image_to_image: ['image', 'image'],
  text_to_video: ['text', 'video'],
  image_to_video: ['image', 'video'],
  video_to_video: ['video', 'video'],
  audio_generation: ['text', 'audio'],
};

/** Which capability tags a modality selection covers — the client-side
 * mirror of `capabilities_for_modalities` used for the live preview and for
 * pre-submit validation, so the admin sees the same result the API will
 * derive after saving. */
function capabilitiesForModalities(
  inputModalities: readonly string[],
  outputModalities: readonly string[],
): MediaCapabilityTag[] {
  const inputs = new Set(inputModalities);
  const outputs = new Set(outputModalities);
  return MEDIA_CAPABILITY_TAGS.filter((tag) => {
    const [input, output] = CAPABILITY_MODALITY_MAP[tag];
    return inputs.has(input) && outputs.has(output);
  });
}

interface EndpointFormState {
  id: string;
  name: string;
  base_url: string;
  api_key: string;
  kind: LlmProviderKind;
  models: string;
  // `kind="media"` only: one model id plus the modalities it supports.
  model: string;
  input_modalities: MediaInputModality[];
  output_modalities: MediaOutputModality[];
  role: 'primary' | 'backup';
  backup_order: string;
  max_concurrency: string;
  timeout_ms: string;
  enabled: boolean;
}

/**
 * Model ids are no longer admin-authored: the endpoint id is just the config
 * dict key, so a random id is exactly as good as a hand-picked slug and
 * removes an input the admin has no reason to think about. `ep_` mirrors the
 * repo's typed-id-prefix convention even though this key never touches
 * `back/app/models/base.py:new_id` — it lives in `PlatformConfig` JSON, not a
 * database row.
 */
function generateModelId(existingIds: Set<string>): string {
  for (let attempt = 0; attempt < 5; attempt += 1) {
    const id = `ep_${globalThis.crypto.randomUUID().replace(/-/g, '').slice(0, 12)}`;
    if (!existingIds.has(id)) return id;
  }
  return `ep_${globalThis.crypto.randomUUID().replace(/-/g, '')}`;
}

function emptyForm(id: string, kind: LlmProviderKind, hasPrimary: boolean): EndpointFormState {
  return {
    id,
    name: '',
    base_url: '',
    api_key: '',
    kind,
    models: '',
    model: '',
    input_modalities: [],
    output_modalities: [],
    role: !hasPrimary ? 'primary' : 'backup',
    backup_order: '100',
    max_concurrency: '4',
    timeout_ms: '30000',
    enabled: true,
  };
}

function formFrom(endpoint: LlmProviderEndpoint): EndpointFormState {
  return {
    id: endpoint.id,
    name: endpoint.name,
    base_url: endpoint.base_url,
    api_key: '',
    kind: endpoint.kind,
    models: (endpoint.models ?? []).join(', '),
    model: endpoint.model ?? '',
    input_modalities: (endpoint.input_modalities ?? []) as MediaInputModality[],
    output_modalities: (endpoint.output_modalities ?? []) as MediaOutputModality[],
    role: endpoint.role,
    backup_order: String(endpoint.backup_order),
    max_concurrency: String(endpoint.max_concurrency),
    timeout_ms: String(endpoint.timeout_ms),
    enabled: endpoint.enabled,
  };
}

function splitList(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

/** Shared shape for `PUT /admin/llm-providers/{id}`, used both by the full
 * editor save and by the list row's quick enable/disable toggle so the two
 * never drift on what a "no-op except one field" write looks like. */
function buildUpsertPayload(form: EndpointFormState) {
  return {
    name: form.name,
    base_url: form.base_url,
    api_key: form.api_key.trim() ? form.api_key.trim() : undefined,
    kind: form.kind,
    models: form.kind === 'general' ? splitList(form.models) : [],
    role: form.role,
    backup_order: Number(form.backup_order),
    model: form.kind === 'media' ? form.model.trim() : '',
    input_modalities: form.kind === 'media' ? form.input_modalities : [],
    output_modalities: form.kind === 'media' ? form.output_modalities : [],
    max_concurrency: Number(form.max_concurrency),
    timeout_ms: Number(form.timeout_ms),
    enabled: form.enabled,
  };
}

/**
 * Model management console: a flat primary/backup list of endpoints
 * (general and media), plus one shared editor dialog.
 *
 * Writes go through `PUT /admin/llm-providers/{id}`, which itself writes
 * through the versioned config centre — so every save here is still
 * audited and rollback-able like any other platform config change.
 * Circuit-breaker/retry knobs live in the config centre's `llm_reliability`
 * entry instead of this panel — they are ops parameters, not part of the
 * model directory.
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
  const primaries = endpoints.filter((endpoint) => endpoint.role === 'primary');
  const backups = endpoints
    .filter((endpoint) => endpoint.role === 'backup')
    .slice()
    .sort((a, b) => a.backup_order - b.backup_order || a.id.localeCompare(b.id));

  const [editing, setEditing] = useState<EndpointFormState | null>(null);
  const [removing, setRemoving] = useState<LlmProviderEndpoint | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const knownIds = new Set(endpoints.map((e) => e.id));

  const hasPrimaryOfKind = (kind: LlmProviderKind) =>
    endpoints.some((endpoint) => endpoint.kind === kind && endpoint.role === 'primary');

  const reload = async () => {
    setPool(await adminApi.get<LlmProviderPool>('/v1/admin/llm-providers'));
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
      if (editing.kind === 'media') {
        if (!editing.model.trim()) {
          setError(t('mediaModelRequired'));
          setBusy(false);
          return;
        }
        if (capabilitiesForModalities(editing.input_modalities, editing.output_modalities).length === 0) {
          setError(t('modalitiesRequired'));
          setBusy(false);
          return;
        }
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
      const updated = await adminApi.put<LlmProviderPool>(`/v1/admin/llm-providers/${endpoint.id}`, payload);
      setPool(updated);
      notify(endpoint.enabled ? t('modelDisabled') : t('modelEnabledNotice'), 'success');
    } catch (caught) {
      notify(caught instanceof ApiError ? caught.message : tAdmin('loadFailed'), 'error');
    } finally {
      setTogglingId(null);
    }
  };

  return (
    <section className="flex flex-col gap-4">
      {endpoints.length === 0 ? (
        <EmptyState
          title={t('listEmpty')}
          description={t('listEmptyDesc')}
          action={
            editable ? (
              <Button size="sm" onClick={openCreate}>
                {t('addProvider')}
              </Button>
            ) : undefined
          }
        />
      ) : (
        <>
          {editable ? (
            <div className="flex justify-end">
              <Button size="sm" onClick={openCreate}>
                {t('addProvider')}
              </Button>
            </div>
          ) : null}

          <div className="rounded-[var(--radius-md)] border border-border bg-surface p-5">
            <div className="flex flex-col gap-4">
              <div>
                <p className="text-xs font-medium text-muted">{t('primaryNode')}</p>
                {primaries.length === 0 ? (
                  <p className="mt-1.5 text-xs text-muted">{t('noPrimary')}</p>
                ) : (
                  <div className="mt-1.5 flex flex-col gap-2">
                    {primaries.map((endpoint) => (
                      <NodeRow
                        key={endpoint.id}
                        endpoint={endpoint}
                        editable={editable}
                        toggling={togglingId === endpoint.id}
                        onEdit={openEdit}
                        onRemove={(item) => setRemoving(item)}
                        onToggleEnabled={toggleEnabled}
                      />
                    ))}
                  </div>
                )}
              </div>

              <div>
                <p className="text-xs font-medium text-muted">{t('backupNodes')}</p>
                {backups.length === 0 ? (
                  <p className="mt-1.5 text-xs text-muted">{t('noBackups')}</p>
                ) : (
                  <div className="mt-1.5 flex flex-col gap-2">
                    {backups.map((endpoint) => (
                      <NodeRow
                        key={endpoint.id}
                        endpoint={endpoint}
                        editable={editable}
                        toggling={togglingId === endpoint.id}
                        onEdit={openEdit}
                        onRemove={(item) => setRemoving(item)}
                        onToggleEnabled={toggleEnabled}
                      />
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </>
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
                    role: hasPrimaryOfKind(kind) ? current.role : 'primary',
                  };
                })
              }
            />

            {editing.kind === 'general' ? (
              <TextInput
                layout="inline"
                label={t('endpointModels')}
                hint={t('endpointModelsHint')}
                value={editing.models}
                onChange={(event) =>
                  setEditing((current) => current && { ...current, models: event.target.value })
                }
              />
            ) : (
              <>
                <TextInput
                  layout="inline"
                  label={t('mediaModelName')}
                  hint={t('mediaModelNameHint')}
                  value={editing.model}
                  onChange={(event) =>
                    setEditing((current) => current && { ...current, model: event.target.value })
                  }
                />
                <ModalitySelector
                  inputModalities={editing.input_modalities}
                  outputModalities={editing.output_modalities}
                  onChange={(next) =>
                    setEditing((current) => current && { ...current, ...next })
                  }
                />
              </>
            )}

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
            <div className="grid gap-3 sm:grid-cols-2">
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
              <TextInput
                layout="inline"
                label={t('timeoutMs')}
                type="number"
                min="1000"
                value={editing.timeout_ms}
                onChange={(event) =>
                  setEditing((current) => current && { ...current, timeout_ms: event.target.value })
                }
              />
            </div>
            {error ? <ErrorNotice title={error} /> : null}
          </div>
        ) : null}
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
                {t(CAPABILITY_LABEL_KEYS[tag])}
              </Badge>
            ))}
          </div>
        )}
      </div>
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

function NodeRow({
  endpoint,
  editable,
  toggling,
  onEdit,
  onRemove,
  onToggleEnabled,
}: {
  endpoint: LlmProviderEndpoint;
  editable: boolean;
  toggling: boolean;
  onEdit: (endpoint: LlmProviderEndpoint) => void;
  onRemove: (endpoint: LlmProviderEndpoint) => void;
  onToggleEnabled: (endpoint: LlmProviderEndpoint) => void;
}) {
  const t = useTranslations('adminProviders');
  const tAdmin = useTranslations('admin');
  const capabilityTags = endpoint.kind === 'media' ? endpoint.capabilities ?? [] : [];

  return (
    <div
      className={
        'flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-sm)] border p-3 ' +
        (endpoint.role === 'primary' ? 'border-accent/40 bg-accent/5' : 'border-border bg-surface-soft')
      }
    >
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-text">{endpoint.name}</span>
          <span className="font-mono text-[11px] text-muted">{endpoint.id}</span>
          <Badge tone="neutral">
            {endpoint.kind === 'general' ? t('modelTypeGeneral') : t('modelTypeMedia')}
          </Badge>
          <Badge tone={endpoint.enabled ? 'success' : 'neutral'}>
            {endpoint.enabled ? t('enabled') : t('disabled')}
          </Badge>
          <Badge tone={endpoint.circuit_breaker_open ? 'danger' : 'success'}>
            {endpoint.circuit_breaker_open ? t('breakerOpen') : t('breakerClosed')}
          </Badge>
        </div>
        <p className="mt-0.5 truncate font-mono text-[11px] text-muted">{endpoint.base_url}</p>
        {endpoint.kind === 'general' && (endpoint.models ?? []).length > 0 ? (
          <p className="mt-0.5 truncate text-[11px] text-muted">{(endpoint.models ?? []).join(', ')}</p>
        ) : null}
        {endpoint.kind === 'media' && endpoint.model ? (
          <p className="mt-0.5 truncate font-mono text-[11px] text-muted">{endpoint.model}</p>
        ) : null}
        {capabilityTags.length > 0 ? (
          <div className="mt-1 flex flex-wrap gap-1">
            {capabilityTags.map((tag) => (
              <Badge key={tag} tone="neutral">
                {t(CAPABILITY_LABEL_KEYS[tag as MediaCapabilityTag] ?? tag)}
              </Badge>
            ))}
          </div>
        ) : null}
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
      </div>
      {editable ? (
        <div className="flex items-center gap-3">
          <InlineToggle
            label={`${endpoint.name} · ${t('modelEnabled')}`}
            checked={endpoint.enabled}
            disabled={toggling}
            onChange={() => onToggleEnabled(endpoint)}
          />
          <div className="flex gap-2">
            <Button size="sm" variant="ghost" onClick={() => onEdit(endpoint)}>
              {tAdmin('detail')}
            </Button>
            <Button size="sm" variant="danger" onClick={() => onRemove(endpoint)}>
              {t('removeModel')}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

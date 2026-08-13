'use client';

import { useTranslations } from 'next-intl';
import { useId, useState } from 'react';

import { useAdminSession } from '@/components/admin/admin-session-provider';
import { DangerConfirm } from '@/components/admin/danger-confirm';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Select, TextInput } from '@/components/ui/field';
import { IconPlay, IconRefresh } from '@/components/ui/icons';
import { Badge, EmptyState, ErrorNotice } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { cn } from '@/lib/cn';
import {
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
import type { MediaInputModality, MediaOutputModality, MediaProtocol } from '@/lib/admin/operations';
import { atLeast } from '@/lib/admin/rbac';
import { adminApi } from '@/lib/api/admin-client';
import type {
  LlmProviderEndpoint,
  LlmProviderKind,
  LlmProviderPool,
  LlmProviderValidationResult,
} from '@/lib/api/admin-types';
import { ApiError } from '@/lib/api/errors';

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
  protocol: MediaProtocol;
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
    models: '',
    model: '',
    input_modalities: [],
    output_modalities: [],
    protocol: 'openai',
    role: !hasPrimary ? 'primary' : 'backup',
    backup_order: '100',
    max_concurrency: '4',
    timeout_ms: kind === 'media' ? '90000' : '30000',
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
    protocol: endpoint.kind === 'media' && endpoint.protocol ? endpoint.protocol : 'openai',
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
    protocol: form.kind === 'media' ? form.protocol : null,
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
  const [validatingIds, setValidatingIds] = useState<Set<string>>(() => new Set());
  const [confirmingValidation, setConfirmingValidation] = useState<LlmProviderEndpoint | null>(
    null,
  );
  const [validationResults, setValidationResults] = useState<
    Record<string, LlmProviderValidationResult>
  >({});
  const knownIds = new Set(endpoints.map((e) => e.id));

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
      if (editing.kind === 'media') {
        if (!editing.model.trim()) {
          setError(t('mediaModelRequired'));
          setBusy(false);
          return;
        }
        if (
          capabilitiesForModalities(editing.input_modalities, editing.output_modalities).length ===
          0
        ) {
          setError(t('modalitiesRequired'));
          setBusy(false);
          return;
        }
      } else if (
        editing.models
          .split(',')
          .map((item) => item.trim())
          .filter(Boolean).length === 0
      ) {
        setError(t('endpointModelsHint'));
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
    setValidatingIds((current) => new Set(current).add(endpoint.id));
    try {
      const result = await adminApi.post<LlmProviderValidationResult>(
        `/v1/admin/llm-providers/${endpoint.id}/validate`,
      );
      setValidationResults((current) => ({ ...current, [endpoint.id]: result }));
      notify(
        result.usable ? t('validationSucceeded') : t('validationFailed'),
        result.usable ? 'success' : 'error',
      );
    } catch (caught) {
      notify(caught instanceof ApiError ? caught.message : tAdmin('loadFailed'), 'error');
    } finally {
      setValidatingIds((current) => {
        const next = new Set(current);
        next.delete(endpoint.id);
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
              {group.endpoints.map((endpoint) => (
                <NodeRow
                  key={endpoint.id}
                  endpoint={endpoint}
                  editable={editable}
                  toggling={togglingId === endpoint.id}
                  validating={validatingIds.has(endpoint.id)}
                  validationResult={validationResults[endpoint.id]}
                  onEdit={openEdit}
                  onRemove={(item) => setRemoving(item)}
                  onToggleEnabled={toggleEnabled}
                  onValidate={requestValidation}
                />
              ))}
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
            )}

            {editing.kind === 'general' ? (
              <>
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
  validating,
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
  validationResult?: LlmProviderValidationResult;
  onEdit: (endpoint: LlmProviderEndpoint) => void;
  onRemove: (endpoint: LlmProviderEndpoint) => void;
  onToggleEnabled: (endpoint: LlmProviderEndpoint) => void;
  onValidate: (endpoint: LlmProviderEndpoint) => void;
}) {
  const t = useTranslations('adminProviders');
  const tAdmin = useTranslations('admin');
  const capabilityTags = endpoint.kind === 'media' ? (endpoint.capabilities ?? []) : [];
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
          ? 'border-accent/40 bg-accent/5'
          : 'border-border bg-surface-soft')
      }
    >
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-text">{endpoint.name}</span>
          <span className="font-mono text-[11px] text-muted">{endpoint.id}</span>
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
        {endpoint.kind === 'general' && (endpoint.models ?? []).length > 0 ? (
          <p className="mt-0.5 truncate text-[11px] text-muted">
            {(endpoint.models ?? []).join(', ')}
          </p>
        ) : null}
        {endpoint.kind === 'media' && endpoint.model ? (
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
        {validationResult ? (
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
        <div className="flex w-full flex-wrap items-center justify-end gap-2 border-t border-border pt-3 lg:w-auto lg:flex-nowrap lg:border-t-0 lg:border-l lg:pt-0 lg:pl-4">
          <InlineToggle
            label={`${endpoint.name} · ${t('modelEnabled')}`}
            checked={endpoint.enabled}
            disabled={toggling}
            onChange={() => onToggleEnabled(endpoint)}
          />
          <Button
            size="sm"
            variant="primary"
            icon={<IconPlay className="size-3.5" />}
            loading={validating}
            onClick={() => onValidate(endpoint)}
          >
            {t('validateModel')}
          </Button>
          <Button size="sm" variant="secondary" onClick={() => onEdit(endpoint)}>
            {tAdmin('detail')}
          </Button>
          <Button size="sm" variant="danger" onClick={() => onRemove(endpoint)}>
            {t('removeModel')}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

'use client';

import { useTranslations } from 'next-intl';
import { useId, useState } from 'react';

import { useAdminSession } from '@/components/admin/admin-session-provider';
import { DangerConfirm } from '@/components/admin/danger-confirm';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Select, Switch, TextInput } from '@/components/ui/field';
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

interface CapabilityFormState {
  model: string;
  enabled: boolean;
}

interface EndpointFormState {
  id: string;
  name: string;
  base_url: string;
  api_key: string;
  kind: LlmProviderKind;
  models: string;
  role: 'primary' | 'backup';
  backup_order: string;
  capabilities: Record<MediaCapabilityTag, CapabilityFormState>;
  max_concurrency: string;
  timeout_ms: string;
  enabled: boolean;
}

function emptyCapabilities(preset?: MediaCapabilityTag): Record<MediaCapabilityTag, CapabilityFormState> {
  const capabilities = {} as Record<MediaCapabilityTag, CapabilityFormState>;
  for (const tag of MEDIA_CAPABILITY_TAGS) {
    capabilities[tag] = { model: '', enabled: tag === preset };
  }
  return capabilities;
}

function emptyForm(kind: LlmProviderKind, hasPrimary: boolean): EndpointFormState {
  return {
    id: '',
    name: '',
    base_url: '',
    api_key: '',
    kind,
    models: '',
    role: !hasPrimary ? 'primary' : 'backup',
    backup_order: '100',
    capabilities: emptyCapabilities(),
    max_concurrency: '4',
    timeout_ms: '30000',
    enabled: true,
  };
}

function formFrom(endpoint: LlmProviderEndpoint): EndpointFormState {
  const capabilities = {} as Record<MediaCapabilityTag, CapabilityFormState>;
  for (const tag of MEDIA_CAPABILITY_TAGS) {
    const existing = endpoint.capabilities?.[tag];
    capabilities[tag] = existing
      ? { model: existing.model, enabled: existing.enabled }
      : { model: '', enabled: false };
  }
  return {
    id: endpoint.id,
    name: endpoint.name,
    base_url: endpoint.base_url,
    api_key: '',
    kind: endpoint.kind,
    models: (endpoint.models ?? []).join(', '),
    role: endpoint.role,
    backup_order: String(endpoint.backup_order),
    capabilities,
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

/**
 * The model-provider directory's console: a flat primary/backup list of
 * endpoints (general and media), plus one shared editor dialog.
 *
 * Writes go through `PUT /admin/llm-providers/{id}`, which itself writes
 * through the versioned config centre — so every save here is still
 * audited and rollback-able like any other platform config change.
 * Circuit-breaker/retry knobs live in the config centre's `llm_reliability`
 * entry instead of this panel — they are ops parameters, not part of the
 * provider directory.
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
  const knownIds = new Set(endpoints.map((e) => e.id));

  const hasPrimaryOfKind = (kind: LlmProviderKind) =>
    endpoints.some((endpoint) => endpoint.kind === kind && endpoint.role === 'primary');

  const reload = async () => {
    setPool(await adminApi.get<LlmProviderPool>('/v1/admin/llm-providers'));
  };

  const openCreate = () => {
    setEditing(emptyForm('general', hasPrimaryOfKind('general')));
  };

  const openEdit = (endpoint: LlmProviderEndpoint) => {
    setEditing(formFrom(endpoint));
  };

  const save = async () => {
    if (!editing) return;
    setBusy(true);
    setError(null);
    try {
      const capabilities: Record<string, { model: string; enabled: boolean }> = {};
      if (editing.kind === 'media') {
        for (const tag of MEDIA_CAPABILITY_TAGS) {
          const capability = editing.capabilities[tag];
          if (!capability.enabled) continue;
          if (!capability.model.trim()) {
            setError(t('capabilityModelRequired'));
            setBusy(false);
            return;
          }
          capabilities[tag] = {
            model: capability.model.trim(),
            enabled: true,
          };
        }
        if (Object.keys(capabilities).length === 0) {
          setError(t('capabilitiesRequired'));
          setBusy(false);
          return;
        }
      }
      const updated = await adminApi.put<LlmProviderPool>(`/v1/admin/llm-providers/${editing.id}`, {
        name: editing.name,
        base_url: editing.base_url,
        api_key: editing.api_key.trim() ? editing.api_key.trim() : undefined,
        kind: editing.kind,
        models: editing.kind === 'general' ? splitList(editing.models) : [],
        role: editing.role,
        backup_order: Number(editing.backup_order),
        capabilities,
        max_concurrency: Number(editing.max_concurrency),
        timeout_ms: Number(editing.timeout_ms),
        enabled: editing.enabled,
      });
      setPool(updated);
      const demoted = updated.demoted_endpoint_ids ?? [];
      if (demoted.length > 0) {
        notify(t('demotedNotice', { count: demoted.length }), 'info');
      }
      notify(t('endpointSaved'), 'success');
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
    notify(t('endpointRemoved'), 'success');
    await reload();
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
                        onEdit={openEdit}
                        onRemove={(item) => setRemoving(item)}
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
                        onEdit={openEdit}
                        onRemove={(item) => setRemoving(item)}
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
        title={editing?.id && knownIds.has(editing.id) ? t('editEndpoint') : t('addEndpoint')}
        footer={
          <>
            <Button variant="ghost" onClick={() => setEditing(null)}>
              {tAdmin('reset')}
            </Button>
            <Button loading={busy} onClick={() => void save()}>
              {tAdmin('save')}
            </Button>
          </>
        }
      >
        {editing ? (
          <div className="flex flex-col gap-4">
            <TextInput
              label={t('endpointId')}
              hint={t('endpointIdHint')}
              value={editing.id}
              disabled={knownIds.has(editing.id)}
              pattern="[a-z0-9_]+"
              onChange={(event) =>
                setEditing((current) => current && { ...current, id: event.target.value })
              }
            />
            <TextInput
              label={t('endpointName')}
              value={editing.name}
              onChange={(event) =>
                setEditing((current) => current && { ...current, name: event.target.value })
              }
            />
            <TextInput
              label={t('baseUrl')}
              hint={editing.kind === 'media' ? t('baseUrlMediaHint') : undefined}
              value={editing.base_url}
              onChange={(event) =>
                setEditing((current) => current && { ...current, base_url: event.target.value })
              }
            />
            <TextInput
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
                label={t('endpointModels')}
                hint={t('endpointModelsHint')}
                value={editing.models}
                onChange={(event) =>
                  setEditing((current) => current && { ...current, models: event.target.value })
                }
              />
            ) : (
              <CapabilitiesTable
                capabilities={editing.capabilities}
                onChange={(tag, next) =>
                  setEditing(
                    (current) =>
                      current && {
                        ...current,
                        capabilities: { ...current.capabilities, [tag]: next },
                      },
                  )
                }
              />
            )}

            <div className="grid gap-3 sm:grid-cols-2">
              <Select
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
                label={t('backupOrder')}
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
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <TextInput
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
                label={t('timeoutMs')}
                type="number"
                min="1000"
                value={editing.timeout_ms}
                onChange={(event) =>
                  setEditing((current) => current && { ...current, timeout_ms: event.target.value })
                }
              />
            </div>
            <Switch
              label={t('endpointEnabled')}
              checked={editing.enabled}
              onChange={(checked) =>
                setEditing((current) => current && { ...current, enabled: checked })
              }
            />
            {error ? <ErrorNotice title={error} /> : null}
          </div>
        ) : null}
      </Dialog>

      <DangerConfirm
        open={removing !== null}
        onClose={() => setRemoving(null)}
        title={t('removeEndpoint')}
        description={t('removeEndpointDesc')}
        reasonLabel={tAdmin('dangerReason')}
        onConfirm={remove}
      />
    </section>
  );
}

function CapabilitiesTable({
  capabilities,
  onChange,
}: {
  capabilities: Record<MediaCapabilityTag, CapabilityFormState>;
  onChange: (tag: MediaCapabilityTag, next: CapabilityFormState) => void;
}) {
  const t = useTranslations('adminProviders');

  return (
    <div className="flex flex-col gap-1">
      <p className="text-sm font-medium text-text">{t('capabilitiesTableTitle')}</p>
      <p className="text-xs text-muted">{t('capabilitiesTableHint')}</p>
      <div className="mt-2 flex flex-col divide-y divide-border rounded-[var(--radius-sm)] border border-border">
        {MEDIA_CAPABILITY_TAGS.map((tag) => {
          const capability = capabilities[tag];
          return (
            <div
              key={tag}
              className="grid grid-cols-1 items-end gap-3 p-3 sm:grid-cols-[minmax(8rem,12rem)_minmax(0,1fr)]"
            >
              <CapabilityToggle
                label={t(CAPABILITY_LABEL_KEYS[tag])}
                checked={capability.enabled}
                onChange={(checked) => onChange(tag, { ...capability, enabled: checked })}
              />
              <TextInput
                label={t('capabilityModel')}
                disabled={!capability.enabled}
                value={capability.model}
                onChange={(event) => onChange(tag, { ...capability, model: event.target.value })}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Compact switch for capability rows — the shared `Switch` is a full settings
 * row (`justify-between` + `py-3`) and misaligns next to labeled inputs. */
function CapabilityToggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (next: boolean) => void;
}) {
  const id = useId();

  return (
    <div className="flex h-11 items-center gap-3">
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cn(
          'relative h-6 w-11 shrink-0 rounded-full transition-colors',
          checked ? 'bg-primary' : 'bg-track',
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
      <label htmlFor={id} className="text-sm font-medium text-text">
        {label}
      </label>
    </div>
  );
}

function NodeRow({
  endpoint,
  editable,
  onEdit,
  onRemove,
}: {
  endpoint: LlmProviderEndpoint;
  editable: boolean;
  onEdit: (endpoint: LlmProviderEndpoint) => void;
  onRemove: (endpoint: LlmProviderEndpoint) => void;
}) {
  const t = useTranslations('adminProviders');
  const tAdmin = useTranslations('admin');
  const enabledCapabilities =
    endpoint.kind === 'media'
      ? Object.entries(endpoint.capabilities ?? {}).filter(([, capability]) => capability.enabled)
      : [];

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
        {enabledCapabilities.length > 0 ? (
          <div className="mt-1 flex flex-wrap gap-1">
            {enabledCapabilities.map(([tag]) => (
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
        <div className="flex gap-2">
          <Button size="sm" variant="ghost" onClick={() => onEdit(endpoint)}>
            {tAdmin('detail')}
          </Button>
          <Button size="sm" variant="danger" onClick={() => onRemove(endpoint)}>
            {t('removeEndpoint')}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

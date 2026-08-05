'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { useAdminSession } from '@/components/admin/admin-session-provider';
import { DangerConfirm } from '@/components/admin/danger-confirm';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Switch, TextInput } from '@/components/ui/field';
import { Badge, ErrorNotice } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { atLeast } from '@/lib/admin/rbac';
import { adminApi } from '@/lib/api/admin-client';
import type { LlmProviderEndpoint, LlmProviderPool } from '@/lib/api/admin-types';
import { ApiError } from '@/lib/api/errors';
import { cn } from '@/lib/cn';

interface EndpointFormState {
  id: string;
  name: string;
  base_url: string;
  api_key: string;
  models: string;
  scenario_tags: string;
  max_concurrency: string;
  priority: string;
  timeout_ms: string;
  enabled: boolean;
}

function emptyForm(): EndpointFormState {
  return {
    id: '',
    name: '',
    base_url: '',
    api_key: '',
    models: '',
    scenario_tags: 'general',
    max_concurrency: '4',
    priority: '100',
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
    models: (endpoint.models ?? []).join(', '),
    scenario_tags: (endpoint.scenario_tags ?? []).join(', '),
    max_concurrency: String(endpoint.max_concurrency),
    priority: String(endpoint.priority),
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
 * The failover pool's console: table of endpoints plus an editor dialog.
 *
 * Writes go through `PUT /admin/llm-providers/{id}`, which itself writes
 * through the versioned config centre — so every save here is still
 * audited and rollback-able like any other platform config change.
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
  const [editing, setEditing] = useState<EndpointFormState | null>(null);
  const [removing, setRemoving] = useState<LlmProviderEndpoint | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = async () => {
    setPool(await adminApi.get<LlmProviderPool>('/v1/admin/llm-providers'));
  };

  const save = async () => {
    if (!editing) return;
    setBusy(true);
    setError(null);
    try {
      await adminApi.put(`/v1/admin/llm-providers/${editing.id}`, {
        name: editing.name,
        base_url: editing.base_url,
        api_key: editing.api_key.trim() ? editing.api_key.trim() : undefined,
        models: splitList(editing.models),
        scenario_tags: splitList(editing.scenario_tags),
        max_concurrency: Number(editing.max_concurrency),
        priority: Number(editing.priority),
        timeout_ms: Number(editing.timeout_ms),
        enabled: editing.enabled,
      });
      notify(t('endpointSaved'), 'success');
      setEditing(null);
      await reload();
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
    <section className="rounded-[var(--radius-md)] border border-border bg-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">{t('sectionLlmPool')}</h2>
          <p className="mt-1 max-w-2xl text-xs text-muted">{t('sectionLlmPoolDesc')}</p>
        </div>
        {editable ? (
          <Button size="sm" onClick={() => setEditing(emptyForm())}>
            {t('addEndpoint')}
          </Button>
        ) : null}
      </div>

      {endpoints.length === 0 ? (
        <p className="mt-4 text-xs text-muted">{t('noEndpoints')}</p>
      ) : (
        <div className="mt-4 overflow-x-auto rounded-[var(--radius-sm)] border border-border">
          <table className="w-full text-left text-xs">
            <thead className="bg-surface-soft text-muted">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">
                  {t('colName')}
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  {t('colScenario')}
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  {t('colConcurrency')}
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  {t('colBreaker')}
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  {t('colSuccessRate')}
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  {t('priority')}
                </th>
                {editable ? (
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    {tAdmin('detail')}
                  </th>
                ) : null}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {endpoints.map((endpoint) => (
                <tr key={endpoint.id}>
                  <th scope="row" className="px-3 py-2 text-left font-normal">
                    <span className="font-medium text-text">{endpoint.name}</span>
                    <span className="ml-2 font-mono text-[11px] text-muted">{endpoint.id}</span>
                    <Badge tone={endpoint.enabled ? 'success' : 'neutral'} className="ml-2">
                      {endpoint.enabled ? t('enabled') : t('disabled')}
                    </Badge>
                    <p className="mt-0.5 font-mono text-[11px] text-muted">{endpoint.base_url}</p>
                  </th>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap gap-1">
                      {(endpoint.scenario_tags ?? []).map((tag) => (
                        <Badge key={tag} tone="neutral">
                          {tag}
                        </Badge>
                      ))}
                    </div>
                  </td>
                  <td className="tabular px-3 py-2 text-muted">
                    {endpoint.concurrency_in_use} / {endpoint.max_concurrency}
                  </td>
                  <td className="px-3 py-2">
                    <Badge tone={endpoint.circuit_breaker_open ? 'danger' : 'success'}>
                      {endpoint.circuit_breaker_open ? t('breakerOpen') : t('breakerClosed')}
                    </Badge>
                  </td>
                  <td className="tabular px-3 py-2 text-muted">
                    {endpoint.recent_success_rate == null
                      ? t('noRecentAttempts')
                      : `${(endpoint.recent_success_rate * 100).toFixed(1)}% (${endpoint.recent_attempts})`}
                  </td>
                  <td className="tabular px-3 py-2 text-muted">{endpoint.priority}</td>
                  {editable ? (
                    <td className="px-3 py-2 text-right">
                      <div className="flex justify-end gap-2">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setEditing(formFrom(endpoint))}
                        >
                          {tAdmin('detail')}
                        </Button>
                        <Button size="sm" variant="danger" onClick={() => setRemoving(endpoint)}>
                          {t('removeEndpoint')}
                        </Button>
                      </div>
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editable ? (
        <BreakerSettingsForm
          pool={pool}
          onSaved={(updated) => {
            setPool(updated);
            notify(t('breakerSaved'), 'success');
          }}
        />
      ) : null}

      <Dialog
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={
          editing?.id && endpoints.some((e) => e.id === editing.id)
            ? t('editEndpoint')
            : t('addEndpoint')
        }
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
              disabled={endpoints.some((e) => e.id === editing.id)}
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
            <TextInput
              label={t('endpointModels')}
              value={editing.models}
              onChange={(event) =>
                setEditing((current) => current && { ...current, models: event.target.value })
              }
            />
            <TextInput
              label={t('scenarioTags')}
              value={editing.scenario_tags}
              onChange={(event) =>
                setEditing(
                  (current) => current && { ...current, scenario_tags: event.target.value },
                )
              }
            />
            <div className="grid gap-3 sm:grid-cols-3">
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
                label={t('priority')}
                type="number"
                min="1"
                value={editing.priority}
                onChange={(event) =>
                  setEditing((current) => current && { ...current, priority: event.target.value })
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

function BreakerSettingsForm({
  pool,
  onSaved,
}: {
  pool: LlmProviderPool;
  onSaved: (pool: LlmProviderPool) => void;
}) {
  const t = useTranslations('adminProviders');
  const tAdmin = useTranslations('admin');
  const [threshold, setThreshold] = useState(String(pool.circuit_breaker_failure_threshold));
  const [cooldown, setCooldown] = useState(String(pool.circuit_breaker_cooldown_s));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const updated = await adminApi.put<LlmProviderPool>(
        '/v1/admin/llm-providers/settings/circuit-breaker',
        {
          circuit_breaker_failure_threshold: Number(threshold),
          circuit_breaker_cooldown_s: Number(cooldown),
        },
      );
      onSaved(updated);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : tAdmin('loadFailed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={cn('mt-5 border-t border-border pt-4')}>
      <h3 className="text-sm font-semibold">{t('breakerSettings')}</h3>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <TextInput
          label={t('failureThreshold')}
          type="number"
          min="1"
          className="w-40"
          value={threshold}
          onChange={(event) => setThreshold(event.target.value)}
        />
        <TextInput
          label={t('cooldownSeconds')}
          type="number"
          min="5"
          className="w-40"
          value={cooldown}
          onChange={(event) => setCooldown(event.target.value)}
        />
        <Button loading={busy} onClick={() => void save()}>
          {tAdmin('apply')}
        </Button>
      </div>
      {error ? (
        <div className="mt-2">
          <ErrorNotice title={error} />
        </div>
      ) : null}
    </div>
  );
}

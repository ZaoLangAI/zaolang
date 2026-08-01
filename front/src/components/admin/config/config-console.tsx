'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { useAdminSession } from '@/components/admin/admin-session-provider';
import { DangerConfirm } from '@/components/admin/danger-confirm';
import { JsonDiff } from '@/components/admin/json-diff';
import { Button } from '@/components/ui/button';
import { TextArea, TextInput } from '@/components/ui/field';
import { Badge, ErrorNotice } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import type { Locale } from '@/i18n/routing';
import { atLeast } from '@/lib/admin/rbac';
import { adminApi } from '@/lib/api/admin-client';
import type { ConfigValue, ConfigVersion, Page } from '@/lib/api/admin-types';
import { ApiError } from '@/lib/api/errors';
import { cn } from '@/lib/cn';
import { formatDateTime } from '@/lib/format';

export function ConfigConsole({ initial }: { initial: ConfigValue[] }) {
  const t = useTranslations('adminConfig');
  const tAdmin = useTranslations('admin');
  const locale = useLocale() as Locale;
  const { notify } = useToast();
  const { role } = useAdminSession();

  const [keys, setKeys] = useState(initial);
  const [activeKey, setActiveKey] = useState(initial[0]?.key ?? '');
  const [history, setHistory] = useState<ConfigVersion[]>([]);
  const [rollbackTo, setRollbackTo] = useState<ConfigVersion | null>(null);

  const active = keys.find((item) => item.key === activeKey);
  const canEdit = atLeast(role, 'admin');

  useEffect(() => {
    if (!activeKey) return;
    let cancelled = false;
    adminApi
      .get<Page<ConfigVersion>>(`/v1/admin/config/${activeKey}/history`)
      .then((page) => {
        if (!cancelled) setHistory(page.items);
      })
      .catch(() => {
        if (!cancelled) setHistory([]);
      });
    return () => {
      cancelled = true;
    };
  }, [activeKey]);

  const refresh = async (key: string) => {
    const [value, page] = await Promise.all([
      adminApi.get<ConfigValue>(`/v1/admin/config/${key}`),
      adminApi.get<Page<ConfigVersion>>(`/v1/admin/config/${key}/history`),
    ]);
    setKeys((current) => current.map((item) => (item.key === key ? value : item)));
    setHistory(page.items);
  };

  const rollback = async (reason: string) => {
    if (!active || !rollbackTo) return;
    await adminApi.post(`/v1/admin/config/${active.key}/rollback`, {
      target_version: rollbackTo.version,
      reason,
      confirm: true,
    });
    notify(t('rolledBack'), 'success');
    await refresh(active.key);
  };

  return (
    <section className="grid gap-5 lg:grid-cols-[220px_minmax(0,1fr)]">
      <nav aria-label={t('keys')}>
        <ul className="flex flex-col gap-1">
          {keys.map((item) => (
            <li key={item.key}>
              <button
                type="button"
                onClick={() => setActiveKey(item.key)}
                className={cn(
                  'flex w-full items-center justify-between gap-2 rounded-[var(--radius-sm)] px-3 py-2 text-left',
                  item.key === activeKey
                    ? 'bg-primary/12 text-primary'
                    : 'text-muted hover:bg-surface-soft hover:text-text',
                )}
              >
                <span className="truncate font-mono text-xs">{item.key}</span>
                <span className="tabular text-[11px] text-muted">v{item.version}</span>
              </button>
            </li>
          ))}
        </ul>
      </nav>

      {active ? (
        <div className="flex min-w-0 flex-col gap-5">
          <ValueEditor
            // Remounting on key or version change resets the draft without an
            // effect, so the textarea never shows another key's JSON.
            key={`${active.key}@${active.version}`}
            config={active}
            canEdit={canEdit}
            onSaved={() => void refresh(active.key)}
          />

          <div>
            <h3 className="mb-2 text-sm font-semibold">{t('history')}</h3>
            {history.length === 0 ? (
              <p className="text-xs text-muted">{tAdmin('empty')}</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {history.map((version) => (
                  <li
                    key={version.version}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-sm)] border border-border bg-surface px-3 py-2"
                  >
                    <span className="min-w-0">
                      <span className="tabular text-xs">v{version.version}</span>
                      {version.is_active ? (
                        <Badge tone="success" className="ml-2">
                          {t('activeVersion')}
                        </Badge>
                      ) : null}
                      <span className="mt-0.5 block truncate text-[11px] text-muted">
                        {formatDateTime(version.created_at, locale)}
                        {version.note ? ` · ${version.note}` : ''}
                      </span>
                    </span>
                    {canEdit && !version.is_active ? (
                      <Button size="sm" variant="ghost" onClick={() => setRollbackTo(version)}>
                        {t('rollback')}
                      </Button>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      ) : (
        <ErrorNotice title={tAdmin('loadFailed')} />
      )}

      <DangerConfirm
        open={rollbackTo !== null}
        onClose={() => setRollbackTo(null)}
        title={t('rollback')}
        description={t('rollbackHint', { version: rollbackTo?.version ?? 0 })}
        reasonLabel={tAdmin('dangerReason')}
        onConfirm={rollback}
      />
    </section>
  );
}

function ValueEditor({
  config,
  canEdit,
  onSaved,
}: {
  config: ConfigValue;
  canEdit: boolean;
  onSaved: () => void;
}) {
  const t = useTranslations('adminConfig');
  const tAdmin = useTranslations('admin');
  const { notify } = useToast();

  const [draft, setDraft] = useState(() => JSON.stringify(config.value, null, 2));
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  let parsed: unknown = config.value;
  let malformed = false;
  try {
    parsed = JSON.parse(draft);
  } catch {
    malformed = true;
  }

  const save = async () => {
    if (malformed) {
      setError(t('invalidJson'));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await adminApi.put(`/v1/admin/config/${config.key}`, {
        value: parsed,
        note: note || undefined,
      });
      notify(t('saved'), 'success');
      onSaved();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t('invalidJson'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <div>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-mono text-sm">{config.key}</h2>
          <Badge tone="neutral">v{config.version}</Badge>
        </div>
        <p className="mb-2 text-xs text-muted">
          {t('fields', { fields: (config.schema_fields ?? []).join(', ') })}
        </p>

        <TextArea
          label={t('value')}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          rows={14}
          disabled={!canEdit}
          className="font-mono text-xs"
          error={error ?? (malformed ? t('invalidJson') : undefined)}
          hint={canEdit ? t('valueHint') : t('readOnly')}
        />

        {canEdit ? (
          <div className="mt-3 flex flex-wrap items-end gap-3">
            <TextInput
              label={t('note')}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              className="min-w-[220px] flex-1"
            />
            <Button size="sm" loading={saving} disabled={malformed} onClick={() => void save()}>
              {tAdmin('save')}
            </Button>
          </div>
        ) : null}
      </div>

      <div>
        <h3 className="mb-2 text-sm font-semibold">{t('pendingDiff')}</h3>
        <JsonDiff before={config.value} after={malformed ? config.value : parsed} />
      </div>
    </>
  );
}

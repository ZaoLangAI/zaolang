'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { useAdminSession } from '@/components/admin/admin-session-provider';
import { Button } from '@/components/ui/button';
import { TextInput } from '@/components/ui/field';
import { ErrorNotice } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { atLeast } from '@/lib/admin/rbac';
import { adminApi } from '@/lib/api/admin-client';
import type { ConfigValue } from '@/lib/api/admin-types';
import { ApiError } from '@/lib/api/errors';

const KEYS = ['quality', 'latency', 'cost', 'reliability'] as const;

/**
 * Editor for the four routing weights.
 *
 * Written through the config centre, so the change is versioned, audited and
 * rollback-able like any other configuration — the router reads the same key.
 */
export function RoutingWeightsPanel({ initial }: { initial: ConfigValue }) {
  const t = useTranslations('adminProviders');
  const tConfig = useTranslations('adminConfig');
  const tAdmin = useTranslations('admin');
  const { notify } = useToast();
  const { role } = useAdminSession();

  const [weights, setWeights] = useState<Record<string, string>>(
    Object.fromEntries(KEYS.map((key) => [key, String(initial.value[key] ?? 0)])),
  );
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Writing a config key is admin-only server-side.
  const editable = atLeast(role, 'admin');
  const labels: Record<(typeof KEYS)[number], string> = {
    quality: t('weightQuality'),
    latency: t('weightLatency'),
    cost: t('weightCost'),
    reliability: t('weightReliability'),
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await adminApi.put('/v1/admin/config/routing_weights', {
        value: {
          ...initial.value,
          ...Object.fromEntries(KEYS.map((key) => [key, Number(weights[key])])),
        },
        note: note.trim() || undefined,
      });
      notify(tConfig('title'), 'success');
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : tAdmin('loadFailed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded-[var(--radius-md)] border border-border bg-surface p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold">{t('weights')}</h2>
        <span className="tabular text-xs text-muted">v{initial.version}</span>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-4">
        {KEYS.map((key) => (
          <TextInput
            key={key}
            label={labels[key]}
            type="number"
            step="0.05"
            min="0"
            max="1"
            disabled={!editable}
            value={weights[key]}
            onChange={(event) =>
              setWeights((current) => ({ ...current, [key]: event.target.value }))
            }
          />
        ))}
      </div>

      {editable ? (
        <div className="mt-4 flex flex-wrap items-end gap-3">
          <div className="min-w-[240px] flex-1">
            <TextInput
              label={tConfig('saveReason')}
              value={note}
              maxLength={300}
              onChange={(event) => setNote(event.target.value)}
            />
          </div>
          <Button loading={busy} onClick={() => void save()}>
            {tAdmin('apply')}
          </Button>
        </div>
      ) : null}

      {error ? (
        <div className="mt-3">
          <ErrorNotice title={error} />
        </div>
      ) : null}
    </section>
  );
}

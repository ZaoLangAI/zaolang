'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { useAdminSession } from '@/components/admin/admin-session-provider';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/field';
import { Badge } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { atLeast } from '@/lib/admin/rbac';
import { adminApi } from '@/lib/api/admin-client';
import type { ConfigValue, FeatureFlag } from '@/lib/api/admin-types';

/**
 * Flags are stored as one `feature_flags` config value, so a toggle writes the
 * whole object back through the same versioned, audited path as any other
 * configuration change.
 */
export function FeatureFlagsPanel({ flags }: { flags: FeatureFlag[] }) {
  const t = useTranslations('adminConfig');
  const tAdmin = useTranslations('admin');
  const { notify } = useToast();
  const { role } = useAdminSession();

  const [state, setState] = useState(flags);
  const [saving, setSaving] = useState(false);
  const canEdit = atLeast(role, 'admin');

  const dirty = state.some(
    (flag, index) =>
      flag.enabled !== flags[index]?.enabled ||
      flag.rollout_percent !== flags[index]?.rollout_percent,
  );

  const save = async () => {
    setSaving(true);
    try {
      const current = await adminApi.get<ConfigValue>('/v1/admin/config/feature_flags');
      const value: Record<string, unknown> = { ...current.value };
      const rollout: Record<string, number> = {};
      for (const flag of state) {
        value[flag.name] = flag.enabled;
        rollout[flag.name] = flag.rollout_percent;
      }
      value.rollout_percentages = rollout;

      await adminApi.put('/v1/admin/config/feature_flags', { value, note: t('flagsNote') });
      notify(t('saved'), 'success');
    } finally {
      setSaving(false);
    }
  };

  const update = (name: string, patch: Partial<FeatureFlag>) => {
    setState((current) =>
      current.map((flag) => (flag.name === name ? { ...flag, ...patch } : flag)),
    );
  };

  return (
    <section>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold">{t('featureFlags')}</h2>
        {canEdit ? (
          <Button
            size="sm"
            variant="secondary"
            disabled={!dirty}
            loading={saving}
            onClick={() => void save()}
          >
            {tAdmin('save')}
          </Button>
        ) : null}
      </div>

      <ul className="grid gap-3 sm:grid-cols-2">
        {state.map((flag) => (
          <li
            key={flag.name}
            className="flex flex-col gap-2 rounded-[var(--radius-md)] border border-border bg-surface p-4"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="font-mono text-xs">{flag.name}</p>
                <p className="mt-0.5 text-[11px] text-muted">{flag.description}</p>
              </div>
              <Badge tone={flag.enabled ? 'success' : 'neutral'}>
                {flag.enabled ? t('flagOn') : t('flagOff')}
              </Badge>
            </div>

            <Switch
              label={t('flagEnabled')}
              checked={flag.enabled}
              disabled={!canEdit}
              onChange={(checked) => update(flag.name, { enabled: checked })}
            />

            <label className="flex items-center gap-2 text-[11px] text-muted">
              {t('rollout')}
              <input
                type="range"
                min={0}
                max={100}
                step={5}
                value={flag.rollout_percent}
                disabled={!canEdit || !flag.enabled}
                onChange={(event) =>
                  update(flag.name, { rollout_percent: Number(event.target.value) })
                }
                className="flex-1 accent-[var(--primary)]"
              />
              <span className="tabular w-9 text-right">{flag.rollout_percent}%</span>
            </label>
          </li>
        ))}
      </ul>
    </section>
  );
}

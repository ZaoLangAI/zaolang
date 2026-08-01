'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { useAdminSession } from '@/components/admin/admin-session-provider';
import { Button } from '@/components/ui/button';
import { useToast } from '@/components/ui/toast';
import { atLeast } from '@/lib/admin/rbac';
import { adminApi } from '@/lib/api/admin-client';

export function LifecyclePanel({ rules }: { rules: Record<string, unknown>[] }) {
  const t = useTranslations('adminData');
  const { notify } = useToast();
  const { role } = useAdminSession();

  const [applied, setApplied] = useState(rules);
  const [busy, setBusy] = useState(false);

  const apply = async () => {
    setBusy(true);
    try {
      const fresh = await adminApi.post<{ lifecycle_rules: Record<string, unknown>[] }>(
        '/v1/admin/storage/lifecycle',
      );
      setApplied(fresh.lifecycle_rules);
      notify(t('lifecycleApplied'), 'success');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold">{t('lifecycle')}</h2>
        {atLeast(role, 'admin') ? (
          <Button size="sm" variant="secondary" loading={busy} onClick={() => void apply()}>
            {t('applyLifecycle')}
          </Button>
        ) : null}
      </div>
      <p className="mb-3 text-xs text-muted">{t('lifecycleHint')}</p>

      {applied.length === 0 ? (
        <p className="text-xs text-muted">{t('noLifecycle')}</p>
      ) : (
        <pre className="overflow-x-auto rounded-[var(--radius-sm)] border border-border bg-surface p-3 font-mono text-[11px] text-muted">
          {JSON.stringify(applied, null, 2)}
        </pre>
      )}
    </section>
  );
}

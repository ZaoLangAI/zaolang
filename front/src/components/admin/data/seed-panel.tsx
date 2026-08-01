'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { useAdminSession } from '@/components/admin/admin-session-provider';
import { DangerConfirm } from '@/components/admin/danger-confirm';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/field';
import { useToast } from '@/components/ui/toast';
import { atLeast } from '@/lib/admin/rbac';
import { adminApi } from '@/lib/api/admin-client';

/** Seeding is refused server-side in production; this is a dev convenience. */
export function SeedPanel() {
  const t = useTranslations('adminData');
  const tAdmin = useTranslations('admin');
  const { notify } = useToast();
  const { role } = useAdminSession();

  const [reset, setReset] = useState(false);
  const [confirming, setConfirming] = useState(false);

  if (!atLeast(role, 'admin')) return null;

  const seed = async (reason: string) => {
    await adminApi.post('/v1/admin/seed', { reset, reason, confirm: true });
    notify(t('seedDone'), 'success');
  };

  return (
    <section>
      <h2 className="text-sm font-semibold">{t('seed')}</h2>
      <p className="mb-3 mt-1 text-xs text-muted">{t('seedHint')}</p>

      <div className="flex flex-wrap items-center gap-4">
        <Switch label={t('seedReset')} checked={reset} onChange={setReset} />
        <Button
          size="sm"
          variant={reset ? 'danger' : 'secondary'}
          onClick={() => setConfirming(true)}
        >
          {reset ? t('seedResetAction') : t('seedAction')}
        </Button>
      </div>

      <DangerConfirm
        open={confirming}
        onClose={() => setConfirming(false)}
        title={reset ? t('seedResetAction') : t('seedAction')}
        description={t('seedResetWarning')}
        reasonLabel={tAdmin('dangerReason')}
        confirmWord={reset ? 'RESET' : undefined}
        onConfirm={seed}
      />
    </section>
  );
}

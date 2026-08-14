'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { UnlockDialog } from '@/components/marketplace/unlock-dialog';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/primitives';
import { Link, useRouter } from '@/i18n/navigation';
import type { WorkDetail } from '@/lib/api/types';

export function RemixUnlockGate({ work }: { work: WorkDetail }) {
  const t = useTranslations('remixPage');
  const tWork = useTranslations('work');
  const tPage = useTranslations('workPage');
  const router = useRouter();
  const [open, setOpen] = useState(false);

  if (work.remix_block_reason !== 'needs_unlock') {
    return (
      <EmptyState
        title={t('notRemixable')}
        description={t('notRemixableHint')}
        action={
          <Link
            href="/discover"
            className="rounded-[var(--radius-sm)] border border-border px-4 py-2 text-sm hover:bg-surface-soft"
          >
            {tPage('backToDiscover')}
          </Link>
        }
      />
    );
  }

  return (
    <>
      <EmptyState
        title={t('needsUnlock')}
        description={t('needsUnlockHint')}
        action={
          <Button onClick={() => setOpen(true)}>
            {t('unlockCta')} · {tWork('paidBadge', { credits: work.access_credits })}
          </Button>
        }
      />
      <UnlockDialog
        open={open}
        onClose={() => setOpen(false)}
        path={`/v1/works/${work.id}/unlock`}
        credits={work.access_credits}
        title={tWork('unlockThis')}
        confirm={tWork('unlockConfirm', { credits: work.access_credits })}
        onUnlocked={() => router.refresh()}
      />
    </>
  );
}

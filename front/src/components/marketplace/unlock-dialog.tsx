'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { ErrorNotice } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { Link } from '@/i18n/navigation';
import { api, newIdempotencyKey } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';

/**
 * Confirms a one-time credit unlock. Callers refresh or continue after
 * `onUnlocked` — this dialog does not navigate on its own.
 */
export function UnlockDialog({
  open,
  onClose,
  path,
  credits,
  title,
  confirm,
  onUnlocked,
}: {
  open: boolean;
  onClose: () => void;
  path: string;
  credits: number;
  title: string;
  confirm: string;
  onUnlocked: () => void;
}) {
  const tWork = useTranslations('work');
  const tPage = useTranslations('workPage');
  const tActions = useTranslations('actions');
  const { notify } = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needsBilling, setNeedsBilling] = useState(false);

  const unlock = async () => {
    setBusy(true);
    setError(null);
    setNeedsBilling(false);
    try {
      await api.post(path, {}, { idempotencyKey: newIdempotencyKey() });
      notify(tWork('unlockDone'), 'success');
      onUnlocked();
      onClose();
    } catch (caught) {
      if (caught instanceof ApiError && caught.isInsufficientCredits) {
        setNeedsBilling(true);
        setError(caught.message);
      } else {
        setError(caught instanceof ApiError ? caught.message : tWork('unlockFailed'));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {tActions('cancel')}
          </Button>
          <Button loading={busy} onClick={() => void unlock()}>
            {busy ? tWork('unlocking') : tWork('unlockThis')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <p className="text-sm leading-relaxed text-muted">{confirm}</p>
        <p className="text-sm font-medium">{tWork('paidBadge', { credits })}</p>
        {error ? <ErrorNotice title={error} /> : null}
        {needsBilling ? (
          <Link href="/billing" className="text-sm text-primary hover:underline">
            {tPage('goBilling')}
          </Link>
        ) : null}
      </div>
    </Dialog>
  );
}

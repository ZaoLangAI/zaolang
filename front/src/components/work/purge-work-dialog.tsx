'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { ErrorNotice } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { api } from '@/lib/api/client';

/**
 * Second confirmation from the recycle bin: hard-delete or tombstone+purge
 * media, depending on whether descendants still cite the work.
 */
export function PurgeWorkDialog({
  workId,
  referenced,
  open,
  onClose,
  onPurged,
}: {
  workId: string;
  referenced: boolean;
  open: boolean;
  onClose: () => void;
  onPurged: () => void;
}) {
  const t = useTranslations('collectionPage');
  const tActions = useTranslations('actions');
  const { notify } = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const purge = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.delete(`/v1/works/${workId}/purge`);
      notify(t('purgeWorkDone'), 'success');
      onPurged();
    } catch {
      setError(t('purgeWorkFailed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={t('purgeWorkConfirmTitle')}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {tActions('cancel')}
          </Button>
          <Button variant="danger" loading={busy} onClick={() => void purge()}>
            {tActions('confirm')}
          </Button>
        </>
      }
    >
      {error ? <ErrorNotice title={error} /> : null}
      <p className="text-sm text-muted">
        {referenced ? t('purgeWorkConfirmBodyReferenced') : t('purgeWorkConfirmBody')}
      </p>
    </Dialog>
  );
}

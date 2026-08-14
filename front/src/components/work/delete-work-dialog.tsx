'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { ErrorNotice } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { api } from '@/lib/api/client';

/**
 * Owner confirmation to move a published work into the recycle bin.
 * Shape matches the draft-delete dialog in the library.
 */
export function DeleteWorkDialog({
  workId,
  open,
  onClose,
  onDeleted,
}: {
  workId: string;
  open: boolean;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const t = useTranslations('collectionPage');
  const tActions = useTranslations('actions');
  const { notify } = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.delete(`/v1/works/${workId}`);
      notify(t('deleteWorkDone'), 'success');
      onDeleted();
    } catch {
      setError(t('deleteWorkFailed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={t('deleteWorkConfirmTitle')}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {tActions('cancel')}
          </Button>
          <Button variant="danger" loading={busy} onClick={() => void remove()}>
            {tActions('confirm')}
          </Button>
        </>
      }
    >
      {error ? <ErrorNotice title={error} /> : null}
      <p className="text-sm text-muted">{t('deleteWorkConfirmBody')}</p>
    </Dialog>
  );
}

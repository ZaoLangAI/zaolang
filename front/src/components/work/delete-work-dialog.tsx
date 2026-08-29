'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { ConfirmDialog } from '@/components/ui/confirm-dialog';
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
    <ConfirmDialog
      open={open}
      onClose={onClose}
      title={t('deleteWorkConfirmTitle')}
      confirmLabel={tActions('confirm')}
      cancelLabel={tActions('cancel')}
      busy={busy}
      error={error}
      onConfirm={() => void remove()}
    >
      <p className="text-sm text-muted">{t('deleteWorkConfirmBody')}</p>
    </ConfirmDialog>
  );
}

'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { ErrorNotice } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import * as editorApi from '@/features/editor/api';
import { isApiError } from '@/lib/api/errors';

/** Owner confirmation to move a `kind=drama` series into the recycle bin. */
export function TrashSeriesDialog({
  seriesId,
  open,
  onClose,
  onTrashed,
}: {
  seriesId: string;
  open: boolean;
  onClose: () => void;
  onTrashed: () => void;
}) {
  const t = useTranslations('editor');
  const tActions = useTranslations('actions');
  const { notify } = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const trash = async () => {
    setBusy(true);
    setError(null);
    try {
      await editorApi.trashDramaSeries(seriesId);
      notify(t('trashSeriesDone'), 'success');
      onTrashed();
    } catch (err: unknown) {
      setError(isApiError(err) ? err.message : t('commandFailed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={t('trashSeriesConfirmTitle')}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {tActions('cancel')}
          </Button>
          <Button variant="danger" loading={busy} onClick={() => void trash()}>
            {tActions('confirm')}
          </Button>
        </>
      }
    >
      {error ? <ErrorNotice title={error} /> : null}
      <p className="text-sm text-muted">{t('trashSeriesConfirmBody')}</p>
    </Dialog>
  );
}

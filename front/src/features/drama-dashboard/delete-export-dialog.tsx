'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { ErrorNotice } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import * as editorApi from '@/features/editor/api';
import { isApiError } from '@/lib/api/errors';

/**
 * Owner confirmation to drop one unpublished export from the episode's
 * 最终成片 list. The bound draft is unbound, not deleted; a published
 * bind still 422s on the server.
 */
export function DeleteExportDialog({
  exportId,
  open,
  onClose,
  onDeleted,
}: {
  exportId: string | null;
  open: boolean;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const t = useTranslations('editor');
  const tActions = useTranslations('actions');
  const { notify } = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const remove = async () => {
    if (!exportId) return;
    setBusy(true);
    setError(null);
    try {
      await editorApi.deleteExport(exportId);
      notify(t('finalCutDeleteDone'), 'success');
      onDeleted();
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
      title={t('finalCutDeleteConfirmTitle')}
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
      <p className="text-sm text-muted">{t('finalCutDeleteConfirmBody')}</p>
    </Dialog>
  );
}

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
 * Owner confirmation to hard-delete an episode. Unpublished cuts /
 * revisions / exports are torn down with the row; a published output
 * still 422s. The caller disables the trigger when
 * `canonical_work_id` or a published export is already present.
 */
export function DeleteEpisodeDialog({
  episodeId,
  open,
  onClose,
  onDeleted,
}: {
  episodeId: string;
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
    setBusy(true);
    setError(null);
    try {
      await editorApi.deleteEpisode(episodeId);
      notify(t('deleteEpisodeDone'), 'success');
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
      title={t('deleteEpisodeConfirmTitle')}
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
      <p className="text-sm text-muted">{t('deleteEpisodeConfirmBody')}</p>
      <p className="mt-2 text-sm text-muted">{t('deleteEpisodeConfirmUnpublished')}</p>
    </Dialog>
  );
}

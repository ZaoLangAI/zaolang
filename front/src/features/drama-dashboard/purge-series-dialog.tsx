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
 * Second confirmation from the recycle bin: permanently deletes a trashed
 * series. Blocked server-side while it still has any episodes
 * (`DramaEpisode.series_id` is `ondelete=RESTRICT`) — `hasEpisodes` lets the
 * dialog show that consequence up front rather than only after a failed
 * click, mirroring `PurgeWorkDialog`'s `referenced` prop.
 */
export function PurgeSeriesDialog({
  seriesId,
  hasEpisodes,
  open,
  onClose,
  onPurged,
}: {
  seriesId: string;
  hasEpisodes: boolean;
  open: boolean;
  onClose: () => void;
  onPurged: () => void;
}) {
  const t = useTranslations('editor');
  const tActions = useTranslations('actions');
  const { notify } = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const purge = async () => {
    setBusy(true);
    setError(null);
    try {
      await editorApi.purgeDramaSeries(seriesId);
      notify(t('purgeSeriesDone'), 'success');
      onPurged();
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
      title={t('purgeSeriesConfirmTitle')}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {tActions('cancel')}
          </Button>
          <Button variant="danger" loading={busy} disabled={hasEpisodes} onClick={() => void purge()}>
            {tActions('confirm')}
          </Button>
        </>
      }
    >
      {error ? <ErrorNotice title={error} /> : null}
      <p className="text-sm text-muted">
        {hasEpisodes ? t('purgeSeriesConfirmBodyBlocked') : t('purgeSeriesConfirmBody')}
      </p>
    </Dialog>
  );
}

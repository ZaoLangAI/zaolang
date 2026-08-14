'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Select } from '@/components/ui/field';
import { ErrorNotice } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { api } from '@/lib/api/client';
import type { Visibility, WorkSummary } from '@/lib/api/types';

const VISIBILITIES: Visibility[] = ['public_remixable', 'public_view_only', 'private'];

/**
 * Owner-only surface opened from a work card in the library: change who can
 * see/remix a published work, or tombstone it for good.
 *
 * Only `library-tabs.tsx` wires this up via `WorkCard`'s `actions` slot, so a
 * stranger browsing discover or a profile never sees the trigger — but the
 * API enforces ownership regardless, this is not the only guard.
 */
export function ManageWorkDialog({
  work,
  open,
  onClose,
  onChanged,
}: {
  work: WorkSummary;
  open: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const t = useTranslations('collectionPage');
  const tVisibility = useTranslations('visibility');
  const tActions = useTranslations('actions');
  const { notify } = useToast();

  const [visibility, setVisibility] = useState<Visibility>(work.visibility);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.patch(`/v1/works/${work.id}/visibility`, { visibility });
      notify(t('visibilityUpdateDone'), 'success');
      onChanged();
    } catch {
      setError(t('visibilityUpdateFailed'));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.delete(`/v1/works/${work.id}`);
      notify(t('deleteWorkDone'), 'success');
      onChanged();
    } catch {
      setConfirmDelete(false);
      setError(t('deleteWorkFailed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title={t('manageWorkTitle')} size="sm">
      <div className="flex flex-col gap-4">
        {error ? <ErrorNotice title={error} /> : null}

        <Select
          label={tVisibility('label')}
          value={visibility}
          onChange={(event) => setVisibility(event.target.value as Visibility)}
          options={VISIBILITIES.map((value) => ({ value, label: tVisibility(value) }))}
        />

        <div className="flex items-center justify-end gap-3">
          <Button variant="ghost" onClick={onClose}>
            {tActions('cancel')}
          </Button>
          <Button
            loading={busy}
            disabled={visibility === work.visibility}
            onClick={() => void save()}
          >
            {tActions('save')}
          </Button>
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-border pt-4">
          <p className="text-xs text-muted">{t('deleteWorkHint')}</p>
          <Button variant="danger" size="sm" onClick={() => setConfirmDelete(true)}>
            {t('deleteWork')}
          </Button>
        </div>
      </div>

      <Dialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title={t('deleteWorkConfirmTitle')}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmDelete(false)}>
              {tActions('cancel')}
            </Button>
            <Button variant="danger" loading={busy} onClick={() => void remove()}>
              {tActions('confirm')}
            </Button>
          </>
        }
      >
        <p className="text-sm text-muted">{t('deleteWorkConfirmBody')}</p>
      </Dialog>
    </Dialog>
  );
}

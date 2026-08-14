'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Switch, TextInput } from '@/components/ui/field';
import { ErrorNotice } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { api } from '@/lib/api/client';
import type { Collection } from '@/lib/api/types';

/**
 * Owner-only surface for one already-created collection: rename it, flip its
 * public/private switch, or delete it outright.
 *
 * Only reachable from the "···" menu on a collection tile in the library —
 * there is no shareable collection detail page yet, so nobody else can even
 * navigate to a collection's contents, let alone edit them.
 */
export function EditCollectionDialog({
  collection,
  onClose,
  onChanged,
}: {
  collection: Collection;
  onClose: () => void;
  onChanged: () => void;
}) {
  const t = useTranslations('collectionPage');
  const tActions = useTranslations('actions');
  const { notify } = useToast();

  const [name, setName] = useState(collection.name);
  const [isPublic, setIsPublic] = useState(collection.is_public);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.patch(`/v1/collections/${collection.id}`, {
        name: name.trim(),
        description: collection.description,
        is_public: isPublic,
      });
      notify(t('updateCollectionDone'), 'success');
      onChanged();
    } catch {
      setError(t('updateCollectionFailed'));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.delete(`/v1/collections/${collection.id}`);
      notify(t('deleteCollectionDone'), 'success');
      onChanged();
    } catch {
      setConfirmDelete(false);
      setError(t('deleteCollectionFailed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onClose={onClose} title={t('editCollectionTitle')} size="sm">
      <form className="flex flex-col gap-4" onSubmit={save} noValidate>
        {error ? <ErrorNotice title={error} /> : null}
        <TextInput
          label={t('collectionName')}
          required
          autoFocus
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        <Switch checked={isPublic} onChange={setIsPublic} label={t('collectionPublic')} />
        <div className="flex items-center justify-end gap-3">
          <Button variant="ghost" onClick={onClose}>
            {tActions('cancel')}
          </Button>
          <Button type="submit" loading={busy} disabled={name.trim().length === 0}>
            {tActions('save')}
          </Button>
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-border pt-4">
          <p className="text-xs text-muted">{t('deleteCollectionHint')}</p>
          <Button
            type="button"
            variant="danger"
            size="sm"
            onClick={() => setConfirmDelete(true)}
          >
            {t('deleteCollection')}
          </Button>
        </div>
      </form>

      <Dialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title={t('deleteCollectionConfirmTitle')}
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
        <p className="text-sm text-muted">{t('deleteCollectionConfirmBody')}</p>
      </Dialog>
    </Dialog>
  );
}

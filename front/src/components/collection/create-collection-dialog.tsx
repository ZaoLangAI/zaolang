'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Switch, TextInput } from '@/components/ui/field';
import { ErrorNotice } from '@/components/ui/primitives';
import { api } from '@/lib/api/client';
import type { Collection } from '@/lib/api/types';

/**
 * Creates a named collection.
 *
 * Shared by the library tab's "new collection" tile and the work page's
 * add-to-collection sheet, so a reader never has to leave one flow to start
 * the other.
 */
export function CreateCollectionDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (collection: Collection) => void;
}) {
  const t = useTranslations('collectionPage');
  const tActions = useTranslations('actions');

  const [name, setName] = useState('');
  const [isPublic, setIsPublic] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const close = () => {
    onClose();
    setName('');
    setIsPublic(false);
    setError(null);
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const collection = await api.post<Collection>('/v1/collections', {
        name: name.trim(),
        is_public: isPublic,
      });
      setName('');
      setIsPublic(false);
      onCreated(collection);
    } catch {
      setError(t('createCollectionFailed'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onClose={close} title={t('newCollection')} size="sm">
      <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
        {error ? <ErrorNotice title={error} /> : null}
        <TextInput
          label={t('collectionName')}
          required
          autoFocus
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        <Switch
          checked={isPublic}
          onChange={setIsPublic}
          label={t('collectionPublic')}
        />
        <div className="flex items-center justify-end gap-3">
          <Button variant="ghost" onClick={close}>
            {tActions('cancel')}
          </Button>
          <Button type="submit" loading={submitting} disabled={name.trim().length === 0}>
            {t('createCollection')}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

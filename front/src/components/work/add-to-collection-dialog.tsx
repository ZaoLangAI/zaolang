'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { CreateCollectionDialog } from '@/components/collection/create-collection-dialog';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { IconCheck, IconPlus } from '@/components/ui/icons';
import { ErrorNotice, Skeleton } from '@/components/ui/primitives';
import { api } from '@/lib/api/client';
import type { Collection, Page } from '@/lib/api/types';
import { useResource } from '@/lib/use-resource';

/**
 * Adds a work to one or more of the viewer's collections.
 *
 * There is no endpoint to list a collection's items, so this only ever adds —
 * it cannot show which collections already hold this work, and it has no
 * "remove" affordance. Removing a work from a collection is a library-side
 * action, not a work-page one.
 */
export function AddToCollectionDialog({
  workId,
  open,
  onClose,
}: {
  workId: string;
  open: boolean;
  onClose: () => void;
}) {
  const t = useTranslations('workPage');
  const tCollection = useTranslations('collectionPage');
  const tActions = useTranslations('actions');

  const list = useResource<Page<Collection>>(open ? '/v1/collections' : null);
  const [collections, setCollections] = useState<Collection[] | null>(null);
  const [added, setAdded] = useState<Set<string>>(new Set());
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  // Mirrors the fetched list into local state so a freshly created collection
  // can be appended without waiting on a refetch.
  const rows = collections ?? list.data?.items ?? [];

  const close = () => {
    onClose();
    setCollections(null);
    setAdded(new Set());
    setError(null);
  };

  const addTo = async (collectionId: string) => {
    setPending(collectionId);
    setError(null);
    try {
      await api.post(`/v1/collections/${collectionId}/items`, undefined, {
        query: { work_id: workId },
      });
      setAdded((current) => new Set(current).add(collectionId));
    } catch {
      setError(t('addToCollectionFailed'));
    } finally {
      setPending(null);
    }
  };

  return (
    <>
      <Dialog open={open} onClose={close} title={t('addToCollectionTitle')} size="sm">
        <div className="flex flex-col gap-4">
          <p className="text-sm text-muted">{t('addToCollectionHint')}</p>
          {error ? <ErrorNotice title={error} /> : null}

          {list.status === 'loading' && !collections ? (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </div>
          ) : list.status === 'failed' && !collections ? (
            <ErrorNotice title={t('addToCollectionLoadFailed')} />
          ) : rows.length === 0 ? (
            <p className="text-sm text-muted">{t('addToCollectionEmpty')}</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {rows.map((collection) => {
                const isAdded = added.has(collection.id);
                return (
                  <li
                    key={collection.id}
                    className="flex items-center justify-between gap-3 rounded-[var(--radius-sm)] border border-border px-3 py-2.5"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{collection.name}</p>
                      <p className="text-xs text-muted">
                        {tCollection('collectionItems', { count: collection.item_count })}
                      </p>
                    </div>
                    <Button
                      size="sm"
                      variant={isAdded ? 'secondary' : 'primary'}
                      icon={
                        isAdded ? (
                          <IconCheck className="size-4" />
                        ) : (
                          <IconPlus className="size-4" />
                        )
                      }
                      disabled={isAdded}
                      loading={pending === collection.id}
                      onClick={() => void addTo(collection.id)}
                    >
                      {isAdded ? t('added') : t('addAction')}
                    </Button>
                  </li>
                );
              })}
            </ul>
          )}

          <Button variant="secondary" icon={<IconPlus className="size-4" />} onClick={() => setCreateOpen(true)}>
            {tCollection('newCollection')}
          </Button>

          <div className="flex justify-end">
            <Button variant="ghost" onClick={close}>
              {tActions('close')}
            </Button>
          </div>
        </div>
      </Dialog>

      <CreateCollectionDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(collection) => {
          setCollections([collection, ...rows]);
          setCreateOpen(false);
          void addTo(collection.id);
        }}
      />
    </>
  );
}

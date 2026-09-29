'use client';

import { useLocale, useTranslations } from 'next-intl';

import { Poster } from '@/components/media/poster';
import { Dialog } from '@/components/ui/dialog';
import { EmptyState, Skeleton } from '@/components/ui/primitives';
import type { Locale } from '@/i18n/routing';
import type { Page, StyleGalleryEntry } from '@/lib/api/types';
import { styleGalleryLabel } from '@/lib/style-gallery';
import { useResource } from '@/lib/use-resource';

/**
 * The system style catalogue picker, shared by the studio's "选择画风" entry
 * point and (indirectly, via the same `/v1/style-gallery` data) the create
 * page's inspiration section.
 *
 * Fetched only while open rather than eagerly on the studio's first render:
 * the catalogue is 24+ image cards and most sessions never open this dialog.
 */
export function StyleGalleryDialog({
  open,
  onClose,
  onSelect,
}: {
  open: boolean;
  onClose: () => void;
  onSelect: (entry: StyleGalleryEntry) => void;
}) {
  const t = useTranslations('styleGallery');
  const locale = useLocale() as Locale;

  const gallery = useResource<Page<StyleGalleryEntry>>(open ? '/v1/style-gallery' : null);
  const entries = gallery.data?.items ?? [];

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={t('dialogTitle')}
      description={t('dialogDescription')}
      size="xl"
    >
      {gallery.status === 'loading' ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {Array.from({ length: 8 }, (_, index) => (
            <Skeleton key={index} className="aspect-[4/5] w-full" />
          ))}
        </div>
      ) : gallery.status === 'failed' ? (
        <EmptyState title={t('loadFailed')} />
      ) : entries.length === 0 ? (
        <EmptyState title={t('empty')} />
      ) : (
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {entries.map((entry) => (
            <li key={entry.id}>
              <button
                type="button"
                onClick={() => onSelect(entry)}
                className="group flex w-full flex-col overflow-hidden rounded-[var(--radius-md)] border border-border text-left transition-colors hover:border-primary focus-visible:outline-2"
              >
                <Poster
                  src={entry.cover_url}
                  // Empty when there is a cover: the caption right below already names
                  // the card, so the image stays decorative rather than doubling the
                  // button's accessible name. Falls back to the real label only for
                  // `Poster`'s no-cover placeholder text.
                  alt={entry.cover_url ? '' : styleGalleryLabel(entry, locale)}
                  aspect="square"
                  sizes="(max-width: 640px) 45vw, 220px"
                  className="rounded-none border-0"
                />
                <span className="px-2.5 py-2 text-xs font-medium leading-snug text-text group-hover:text-primary">
                  {styleGalleryLabel(entry, locale)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Dialog>
  );
}

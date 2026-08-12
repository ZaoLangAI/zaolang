import { getLocale, getTranslations } from 'next-intl/server';

import { Poster } from '@/components/media/poster';
import { EmptyState, SectionHeading } from '@/components/ui/primitives';
import { Link } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import type { StyleGalleryEntry } from '@/lib/api/types';
import { styleGalleryLabel } from '@/lib/style-gallery';

/**
 * "Inspiration recommendations": the same system style catalogue that backs
 * the studio's style picker dialog (`/v1/style-gallery`), rendered here as a
 * gallery wall instead of a popup. Picking a card seeds `/create/new` with
 * that style's params through `?styleId=`, exactly as the dialog's `/apply`
 * does inside the studio.
 */
export async function InspirationRecommendations({ entries }: { entries: StyleGalleryEntry[] }) {
  const t = await getTranslations('createPage');
  const locale = (await getLocale()) as Locale;

  return (
    <section>
      <SectionHeading title={t('inspirationTitle')} description={t('inspirationHint')} />

      {entries.length === 0 ? (
        <EmptyState title={t('inspirationEmpty')} />
      ) : (
        <ul className="no-scrollbar flex gap-4 overflow-x-auto pb-1">
          {entries.map((entry) => (
            <li key={entry.id} className="w-36 shrink-0 sm:w-44">
              <Link
                href={{ pathname: '/create/new', query: { mode: 'text_to_video', styleId: entry.id } }}
                className="block"
              >
                <Poster
                  src={entry.cover_url}
                  // Empty when there is a cover: the caption right below already names
                  // the card, so the image stays decorative rather than doubling the
                  // link's accessible name. Falls back to the real label only for
                  // `Poster`'s no-cover placeholder text.
                  alt={entry.cover_url ? '' : styleGalleryLabel(entry, locale)}
                  aspect="square"
                  sizes="(max-width: 640px) 40vw, 176px"
                  className="border border-border"
                />
                <p className="mt-2 truncate text-xs font-medium text-text">
                  {styleGalleryLabel(entry, locale)}
                </p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

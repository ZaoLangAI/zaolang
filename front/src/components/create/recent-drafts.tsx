import { getLocale, getTranslations } from 'next-intl/server';

import { Poster } from '@/components/media/poster';
import { EmptyState, SectionHeading } from '@/components/ui/primitives';
import { Link } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import type { Draft } from '@/lib/api/types';
import { formatRelative } from '@/lib/format';

export async function RecentDrafts({ drafts }: { drafts: Draft[] }) {
  const t = await getTranslations('createPage');
  const tActions = await getTranslations('actions');
  const locale = (await getLocale()) as Locale;

  const newest = drafts[0];

  return (
    <section>
      <SectionHeading
        title={t('recentDrafts')}
        description={
          newest ? t('autoSaved', { when: formatRelative(newest.created_at, locale) }) : undefined
        }
        action={
          drafts.length > 0 ? (
            <Link href="/collection?tab=drafts" className="text-xs text-muted hover:text-text">
              {tActions('viewAll')}
            </Link>
          ) : null
        }
      />

      {drafts.length === 0 ? (
        <EmptyState title={t('noDrafts')} description={t('noDraftsHint')} />
      ) : (
        <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          {drafts.map((draft) => (
            <li key={draft.id}>
              <Link href={`/publish/${draft.id}`} className="block">
                <Poster
                  src={draft.output_url}
                  alt={draft.title ?? t('recentDrafts')}
                  aspect="video"
                  className="border border-border"
                />
                <p className="mt-2 truncate text-xs">{draft.title ?? t('recentDrafts')}</p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

import { getLocale, getTranslations } from 'next-intl/server';

import { LibraryTabs } from '@/components/collection/library-tabs';
import { SignInPrompt } from '@/components/auth/sign-in-prompt';
import { Button } from '@/components/ui/button';
import { PageHeading, StatRow, StatTile } from '@/components/ui/primitives';
import { Link } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import { serverFetchOrNull } from '@/lib/api/server';
import type { Collection, CreationSkillSummary, Draft, Me, Page, WorkSummary } from '@/lib/api/types';
import { formatCount } from '@/lib/format';

export async function generateMetadata() {
  const t = await getTranslations('collectionPage');
  return { title: t('title'), description: t('subtitle') };
}

export default async function CollectionPage({
  searchParams,
}: {
  searchParams: Promise<{ tab?: string }>;
}) {
  const { tab } = await searchParams;
  const t = await getTranslations('collectionPage');
  const locale = (await getLocale()) as Locale;

  const me = await serverFetchOrNull<Me>('/v1/auth/me', { authenticated: true });
  if (!me?.profile) return <SignInPrompt />;

  const [works, drafts, bookmarks, collections, skills] = await Promise.all([
    serverFetchOrNull<Page<WorkSummary>>(`/v1/profiles/${me.profile.handle}/works`, {
      authenticated: true,
      query: { limit: 60 },
    }),
    serverFetchOrNull<Page<Draft>>('/v1/drafts', { authenticated: true }),
    serverFetchOrNull<Page<WorkSummary>>('/v1/me/bookmarks', {
      authenticated: true,
      query: { limit: 60 },
    }),
    serverFetchOrNull<Page<Collection>>('/v1/collections', { authenticated: true }),
    serverFetchOrNull<Page<CreationSkillSummary>>('/v1/skills', { authenticated: true }),
  ]);

  const allWorks = works?.items ?? [];
  const published = allWorks.filter((work) => work.visibility.startsWith('public'));
  const isPrivate = allWorks.filter((work) => work.visibility === 'private');
  const views = allWorks.reduce((sum, work) => sum + work.stats.view_count, 0);

  return (
    <div className="mx-auto flex w-full max-w-[1160px] flex-col gap-6 px-4 py-8 sm:px-6">
      <PageHeading
        eyebrow={t('eyebrow')}
        title={t('title')}
        description={t('subtitle')}
        actions={
          <Link href="/create">
            <Button>{t('newWork')}</Button>
          </Link>
        }
      />

      <StatRow>
        <StatTile value={formatCount(allWorks.length, locale)} label={t('statAll')} />
        <StatTile value={formatCount(published.length, locale)} label={t('statPublished')} />
        <StatTile value={formatCount(drafts?.items.length ?? 0, locale)} label={t('statDrafts')} />
        <StatTile value={formatCount(isPrivate.length, locale)} label={t('statPrivate')} />
        <StatTile value={formatCount(views, locale)} label={t('statViews')} />
      </StatRow>

      <LibraryTabs
        initialTab={tab}
        works={allWorks}
        published={published}
        privateWorks={isPrivate}
        drafts={drafts?.items ?? []}
        bookmarks={bookmarks?.items ?? []}
        collections={collections?.items ?? []}
        skills={skills?.items ?? []}
      />
    </div>
  );
}

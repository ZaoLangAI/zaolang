import { notFound } from 'next/navigation';
import { getLocale, getTranslations } from 'next-intl/server';

import { ActivityFeed } from '@/components/profile/activity-feed';
import { ProfileHeader } from '@/components/profile/profile-header';
import { WorkCard } from '@/components/work/work-card';
import { IconBell, IconChevronRight, IconGear, IconGrid, IconWallet } from '@/components/ui/icons';
import { Badge, EmptyState, SectionHeading, StatRow, StatTile } from '@/components/ui/primitives';
import { Link } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import { serverFetch, serverFetchOrNull } from '@/lib/api/server';
import type {
  CountResponseLike,
  GenerationJob,
  Me,
  Page,
  PublicProfile,
  WorkSummary,
} from '@/lib/api/types';
import { formatCount } from '@/lib/format';

interface Params {
  params: Promise<{ handle: string }>;
}

export async function generateMetadata({ params }: Params) {
  const { handle } = await params;
  const profile = await serverFetchOrNull<PublicProfile>(`/v1/profiles/${handle}`);
  const t = await getTranslations('profilePage');
  return {
    title: profile ? profile.display_name : t('privateProfile'),
    description: profile?.bio ?? undefined,
  };
}

export default async function ProfilePage({ params }: Params) {
  const { handle } = await params;
  const t = await getTranslations('profilePage');
  const tCredits = await getTranslations('credits');
  const locale = (await getLocale()) as Locale;

  const profile = await serverFetchOrNull<PublicProfile>(`/v1/profiles/${handle}`, {
    authenticated: true,
  });
  if (!profile) notFound();

  const works = await serverFetch<Page<WorkSummary>>(`/v1/profiles/${handle}/works`, {
    authenticated: true,
    query: { limit: 12 },
  });

  // The owner's page also shows the private half of their activity.
  const [me, bookmarks, jobs, unread] = profile.is_self
    ? await Promise.all([
        serverFetchOrNull<Me>('/v1/auth/me', { authenticated: true }),
        serverFetchOrNull<Page<WorkSummary>>('/v1/me/bookmarks', {
          authenticated: true,
          query: { limit: 5 },
        }),
        serverFetchOrNull<Page<GenerationJob>>('/v1/generation-jobs', {
          authenticated: true,
          query: { limit: 5 },
        }),
        serverFetchOrNull<CountResponseLike>('/v1/notifications/unread-count', {
          authenticated: true,
        }),
      ])
    : [null, null, null, null];

  const likes = works.items.reduce((sum, work) => sum + work.stats.like_count, 0);
  const views = works.items.reduce((sum, work) => sum + work.stats.view_count, 0);
  const remixes = works.items.reduce((sum, work) => sum + work.stats.remix_count, 0);
  const styleTags = [...new Set(works.items.flatMap((work) => work.tags ?? []))].slice(0, 4);

  return (
    <div className="mx-auto flex w-full max-w-[1160px] flex-col gap-5 px-4 py-6 sm:px-6">
      <ProfileHeader profile={profile} />

      <StatRow>
        <StatTile value={formatCount(profile.work_count, locale)} label={t('statWorks')} />
        <StatTile value={formatCount(views, locale)} label={t('statViews')} />
        <StatTile value={formatCount(likes, locale)} label={t('statLikes')} />
        <StatTile value={formatCount(profile.follower_count, locale)} label={t('statFollowers')} />
        <StatTile value={formatCount(remixes, locale)} label={t('statRemixes')} />
      </StatRow>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.9fr)_minmax(0,1fr)]">
        <div className="flex flex-col gap-5">
          <section className="rounded-[var(--radius-md)] border border-border bg-surface p-5">
            <h2 className="text-base font-semibold">{t('creatorProfile')}</h2>
            <p className="mt-1 text-xs text-muted">{t('creatorProfileHint')}</p>
            <p className="mt-4 text-sm leading-relaxed">{profile.bio ?? t('noBio')}</p>
            {styleTags.length > 0 ? (
              <ul className="mt-4 flex flex-wrap gap-2" aria-label={t('styleTags')}>
                {styleTags.map((tag) => (
                  <li key={tag}>
                    <Badge>{tag}</Badge>
                  </li>
                ))}
              </ul>
            ) : null}
          </section>

          {profile.is_self ? (
            <ActivityFeed
              works={works.items}
              bookmarks={bookmarks?.items ?? []}
              jobs={jobs?.items ?? []}
            />
          ) : null}
        </div>

        {profile.is_self ? (
          <nav aria-label={t('eyebrow')} className="flex flex-col gap-3">
            <QuickLink
              href="/billing"
              icon={<IconWallet className="size-4 text-primary" />}
              title={tCredits('amount', { count: formatCount(me?.available_credits ?? 0, locale) })}
              description={t('linkCreditsDesc')}
            />
            <QuickLink
              href="/collection"
              icon={<IconGrid className="size-4 text-primary" />}
              title={t('linkCollection')}
              description={t('linkCollectionDesc')}
            />
            <QuickLink
              href="/notifications"
              icon={<IconBell className="size-4 text-primary" />}
              title={t('linkNotifications')}
              description={t('linkNotificationsDesc', { count: unread?.count ?? 0 })}
            />
            <QuickLink
              href="/profile/settings"
              icon={<IconGear className="size-4 text-primary" />}
              title={t('linkSettings')}
              description={t('linkSettingsDesc')}
            />
          </nav>
        ) : null}
      </div>

      <section>
        <SectionHeading title={t('worksTab')} />
        {works.items.length === 0 ? (
          <EmptyState title={t('noActivity')} />
        ) : (
          <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
            {works.items.map((work) => (
              <li key={work.id}>
                <WorkCard work={work} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function QuickLink({
  href,
  icon,
  title,
  description,
}: {
  href: string;
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <Link
      href={href}
      className="flex items-center gap-3 rounded-[var(--radius-md)] border border-border bg-surface px-4 py-4 transition-colors hover:bg-surface-soft"
    >
      <span className="grid size-8 shrink-0 place-items-center rounded-[8px] bg-primary/12">
        {icon}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-semibold">{title}</span>
        <span className="block truncate text-xs text-muted">{description}</span>
      </span>
      <IconChevronRight className="size-4 shrink-0 text-muted" />
    </Link>
  );
}

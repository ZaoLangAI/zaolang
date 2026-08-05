import { getTranslations } from 'next-intl/server';

import { Poster } from '@/components/media/poster';
import { Button } from '@/components/ui/button';
import { IconRemix, IconShield } from '@/components/ui/icons';
import { Badge, EmptyState, SectionHeading } from '@/components/ui/primitives';
import { Link } from '@/i18n/navigation';
import { serverFetchOrNull } from '@/lib/api/server';
import type { LearnPostLevel, LearnPostSummary, Page } from '@/lib/api/types';

const LEVEL_LABEL_KEY: Record<LearnPostLevel, string> = {
  beginner: 'levelBeginner',
  intermediate: 'levelIntermediate',
  advanced: 'levelAdvanced',
};

export async function generateMetadata() {
  const t = await getTranslations('learnPage');
  return { title: t('heroTitle'), description: t('heroSubtitle') };
}

export default async function LearnPage() {
  const t = await getTranslations('learnPage');

  const page = await serverFetchOrNull<Page<LearnPostSummary>>('/v1/learn/posts', {
    query: { limit: 12 },
    revalidate: 60,
  });
  const posts = page?.items ?? [];
  // 最新一条通过审核的内容撑起 hero；没有任何发表时退化成纯文字引导，而不是
  // 报错或留一块空白封面。
  const hero = posts[0];

  return (
    <div className="mx-auto flex w-full max-w-[1160px] flex-col gap-8 px-4 py-6 sm:px-6">
      <section className="grid overflow-hidden rounded-[var(--radius-lg)] border border-border bg-surface lg:grid-cols-2">
        <div className="flex flex-col justify-center gap-4 p-8 sm:p-10">
          <p className="eyebrow">{t('eyebrow')}</p>
          <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">
            {hero?.title ?? t('heroTitle')}
          </h1>
          <p className="max-w-lg text-sm leading-relaxed text-muted">
            {hero?.summary ?? t('heroSubtitle')}
          </p>
          <Link href={hero ? `/learn/${hero.id}` : '/create'} className="w-fit">
            <Button size="lg" icon={<IconRemix className="size-5" />}>
              {t('startFirst')}
            </Button>
          </Link>
        </div>
        <Poster
          src={hero?.cover_url}
          alt={hero?.title ?? t('heroTitle')}
          aspect="video"
          priority
          className="rounded-none lg:h-full"
        />
      </section>

      <section>
        <SectionHeading title={t('listTitle')} description={t('listHint')} />
        {posts.length > 0 ? (
          <ol className="grid gap-4 md:grid-cols-3">
            {posts.map((post) => (
              <li
                key={post.id}
                className="overflow-hidden rounded-[var(--radius-md)] border border-border bg-surface transition-colors hover:border-border-strong"
              >
                <Link
                  href={`/learn/${post.id}`}
                  className="block outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--primary)]"
                >
                  <Poster
                    src={post.cover_url}
                    alt={post.title}
                    aspect="video"
                    className="rounded-none"
                  />
                  <div className="p-4">
                    <Badge tone="amber">{t(LEVEL_LABEL_KEY[post.level])}</Badge>
                    <h3 className="mt-1.5 text-sm font-semibold">{post.title}</h3>
                    <p className="mt-1.5 line-clamp-2 text-xs leading-relaxed text-muted">
                      {post.summary}
                    </p>
                    <p className="mt-3 text-[11px] text-muted">
                      {t('byAuthor', { name: post.author.display_name })}
                    </p>
                  </div>
                </Link>
              </li>
            ))}
          </ol>
        ) : (
          <EmptyState title={t('empty')} description={t('emptyHint')} />
        )}
      </section>

      <section className="flex flex-wrap items-center justify-between gap-4 rounded-[var(--radius-lg)] border border-border bg-surface p-6">
        <div className="flex gap-4">
          <span className="grid size-9 shrink-0 place-items-center rounded-[10px] bg-amber/15 text-amber">
            <IconShield className="size-5" />
          </span>
          <div>
            <p className="eyebrow">{t('safetyEyebrow')}</p>
            <h2 className="mt-1 text-lg font-semibold">{t('safetyTitle')}</h2>
            <p className="mt-1.5 max-w-2xl text-xs leading-relaxed text-muted">{t('safetyBody')}</p>
          </div>
        </div>
        {hero ? (
          <Link href={`/learn/${hero.id}`}>
            <Button variant="secondary">{t('viewExample')}</Button>
          </Link>
        ) : null}
      </section>
    </div>
  );
}

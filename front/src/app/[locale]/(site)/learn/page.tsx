import { getTranslations } from 'next-intl/server';

import { Poster } from '@/components/media/poster';
import { Button } from '@/components/ui/button';
import { IconRemix, IconShield } from '@/components/ui/icons';
import { SectionHeading } from '@/components/ui/primitives';
import { Link } from '@/i18n/navigation';
import { serverFetchOrNull } from '@/lib/api/server';
import type { Page, WorkSummary } from '@/lib/api/types';
import { formatDuration } from '@/lib/format';

const COURSES = [
  { index: 1, level: 'levelBeginner', title: 'course1Title', desc: 'course1Desc', seconds: 320 },
  {
    index: 2,
    level: 'levelIntermediate',
    title: 'course2Title',
    desc: 'course2Desc',
    seconds: 525,
  },
  { index: 3, level: 'levelRequired', title: 'course3Title', desc: 'course3Desc', seconds: 370 },
] as const;

export async function generateMetadata() {
  const t = await getTranslations('learnPage');
  return { title: t('heroTitle'), description: t('heroSubtitle') };
}

export default async function LearnPage() {
  const t = await getTranslations('learnPage');

  // Real community works illustrate the lessons; the alternative would be
  // placeholder art, which the design forbids.
  const examples = await serverFetchOrNull<Page<WorkSummary>>('/v1/works', {
    query: { sort: 'popular', remixable: true, limit: 4 },
    revalidate: 300,
  });
  const covers = examples?.items ?? [];

  return (
    <div className="mx-auto flex w-full max-w-[1160px] flex-col gap-8 px-4 py-6 sm:px-6">
      <section className="grid overflow-hidden rounded-[var(--radius-lg)] border border-border bg-surface lg:grid-cols-2">
        <div className="flex flex-col justify-center gap-4 p-8 sm:p-10">
          <p className="eyebrow">{t('eyebrow')}</p>
          <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">{t('heroTitle')}</h1>
          <p className="max-w-lg text-sm leading-relaxed text-muted">{t('heroSubtitle')}</p>
          <Link href="/create" className="w-fit">
            <Button size="lg" icon={<IconRemix className="size-5" />}>
              {t('startFirst')}
            </Button>
          </Link>
        </div>
        <Poster
          src={covers[3]?.cover_url ?? covers[0]?.cover_url}
          alt={t('heroTitle')}
          aspect="video"
          priority
          className="rounded-none lg:h-full"
        />
      </section>

      <section>
        <SectionHeading title={t('paths')} description={t('pathsHint')} />
        <ol className="grid gap-4 md:grid-cols-3">
          {COURSES.map((course, position) => (
            <li
              key={course.index}
              className="overflow-hidden rounded-[var(--radius-md)] border border-border bg-surface"
            >
              <Poster
                src={covers[position]?.cover_url}
                alt={t(course.title)}
                aspect="video"
                className="rounded-none"
              >
                <span className="tabular absolute bottom-2 right-2 rounded bg-surface/85 px-1.5 py-0.5 text-[11px]">
                  {formatDuration(course.seconds)}
                </span>
              </Poster>
              <div className="p-4">
                <p className="text-[11px] text-amber">{t(course.level)}</p>
                <h3 className="mt-1.5 text-sm font-semibold">{t(course.title)}</h3>
                <p className="mt-1.5 text-xs leading-relaxed text-muted">{t(course.desc)}</p>
                <p className="mt-3 text-[11px] text-muted">
                  {t('lesson', { index: course.index })} · {t('includesPractice')}
                </p>
              </div>
            </li>
          ))}
        </ol>
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
        {covers[0] ? (
          <Link href={`/work/${covers[0].id}`}>
            <Button variant="secondary">{t('viewExample')}</Button>
          </Link>
        ) : null}
      </section>
    </div>
  );
}

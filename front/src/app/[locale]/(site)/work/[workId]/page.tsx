import { notFound } from 'next/navigation';
import { getTranslations } from 'next-intl/server';

import { WorkInfoPanel } from '@/components/work/work-info-panel';
import { WorkStage } from '@/components/work/work-stage';
import { WorkCard } from '@/components/work/work-card';
import { Badge, EmptyState, SectionHeading } from '@/components/ui/primitives';
import { IconTombstone } from '@/components/ui/icons';
import { serverFetch, serverFetchOrNull } from '@/lib/api/server';
import type { Page, WorkDetail, WorkSummary } from '@/lib/api/types';

interface Params {
  params: Promise<{ workId: string }>;
}

export async function generateMetadata({ params }: Params) {
  const { workId } = await params;
  const work = await serverFetchOrNull<WorkDetail>(`/v1/works/${workId}`);
  if (!work) {
    const t = await getTranslations('workPage');
    return { title: t('notFound') };
  }
  return {
    title: `${work.title} · ${work.author.display_name}`,
    description: work.description ?? undefined,
  };
}

export default async function WorkPage({ params }: Params) {
  const { workId } = await params;
  const t = await getTranslations('work');
  const tPage = await getTranslations('workPage');

  const work = await serverFetchOrNull<WorkDetail>(`/v1/works/${workId}`, { authenticated: true });
  if (!work) notFound();

  const similar = await serverFetch<Page<WorkSummary>>(`/v1/works/${workId}/similar`, {
    query: { limit: 6 },
  }).catch(() => ({ items: [] }) as Page<WorkSummary>);

  return (
    <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-10 px-4 py-6 sm:px-6">
      {work.lifecycle_status === 'tombstone' ? (
        <div className="flex items-center gap-3 rounded-[var(--radius-sm)] border border-danger/40 bg-danger/8 px-4 py-3">
          <IconTombstone className="size-5 shrink-0 text-danger" />
          <div>
            <p className="text-sm font-medium text-danger">{t('tombstoned')}</p>
            <p className="text-xs text-muted">{t('tombstonedHint')}</p>
          </div>
        </div>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.72fr)_minmax(0,1fr)]">
        <div className="flex flex-col gap-5">
          <WorkStage work={work} />

          {work.tags && work.tags.length > 0 ? (
            <div>
              <h2 className="mb-2 text-sm font-semibold">{tPage('tags')}</h2>
              <ul className="flex flex-wrap gap-2">
                {work.tags.map((tag) => (
                  <li key={tag}>
                    <Badge>{tag}</Badge>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>

        <aside className="rounded-[var(--radius-lg)] border border-border bg-surface p-5 lg:p-6">
          <WorkInfoPanel work={work} />
        </aside>
      </div>

      <section>
        <SectionHeading title={tPage('relatedTitle')} description={tPage('relatedHint')} />
        {similar.items.length > 0 ? (
          <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
            {similar.items.map((item) => (
              <li key={item.id}>
                <WorkCard work={item} />
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title={tPage('similarEmpty')} />
        )}
      </section>
    </div>
  );
}

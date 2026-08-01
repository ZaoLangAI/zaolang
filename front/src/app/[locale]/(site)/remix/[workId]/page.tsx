import { notFound } from 'next/navigation';
import { getTranslations } from 'next-intl/server';

import { GenerationStudio } from '@/components/studio/generation-studio';
import { IconArrowLeft } from '@/components/ui/icons';
import { EmptyState } from '@/components/ui/primitives';
import { Link } from '@/i18n/navigation';
import { serverFetchOrNull } from '@/lib/api/server';
import type { WorkDetail } from '@/lib/api/types';

interface Params {
  params: Promise<{ workId: string }>;
}

export async function generateMetadata({ params }: Params) {
  const { workId } = await params;
  const work = await serverFetchOrNull<WorkDetail>(`/v1/works/${workId}`);
  const t = await getTranslations('remixPage');
  return { title: work ? t('titleFrom', { title: work.title }) : t('eyebrow') };
}

export default async function RemixPage({ params }: Params) {
  const { workId } = await params;
  const t = await getTranslations('remixPage');

  const work = await serverFetchOrNull<WorkDetail>(`/v1/works/${workId}`, { authenticated: true });
  if (!work) notFound();

  return (
    <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-5 px-4 py-6 sm:px-6">
      <Link
        href={`/work/${work.id}`}
        className="flex w-fit items-center gap-1.5 text-sm text-muted hover:text-text"
      >
        <IconArrowLeft className="size-4" />
        {t('backToSource')}
      </Link>

      <header>
        <p className="eyebrow">{t('eyebrow')}</p>
        <h1 className="mt-1.5 text-3xl font-bold tracking-tight sm:text-4xl">
          {t('titleFrom', { title: work.title })}
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-muted">{t('subtitle')}</p>
      </header>

      {work.can_remix && work.reusable_params ? (
        <GenerationStudio
          operation="image_to_video"
          source={{ work, params: work.reusable_params }}
        />
      ) : (
        <EmptyState
          title={t('notRemixable')}
          description={t('notRemixableHint')}
          action={
            <Link
              href="/discover"
              className="rounded-[var(--radius-sm)] border border-border px-4 py-2 text-sm hover:bg-surface-soft"
            >
              {t('backToSource')}
            </Link>
          }
        />
      )}
    </div>
  );
}

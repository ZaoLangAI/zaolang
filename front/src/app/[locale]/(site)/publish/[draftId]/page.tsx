import { notFound } from 'next/navigation';
import { getTranslations } from 'next-intl/server';

import { PublishForm } from '@/components/publish/publish-form';
import { GoBackLink } from '@/components/ui/go-back-link';
import { PageHeading } from '@/components/ui/primitives';
import { serverFetchOrNull } from '@/lib/api/server';
import type { Draft } from '@/lib/api/types';

interface Params {
  params: Promise<{ draftId: string }>;
}

export async function generateMetadata() {
  const t = await getTranslations('publishPage');
  return { title: t('title') };
}

export default async function PublishPage({ params }: Params) {
  const { draftId } = await params;
  const t = await getTranslations('publishPage');
  const tCreate = await getTranslations('createPage');

  const draft = await serverFetchOrNull<Draft>(`/v1/drafts/${draftId}`, { authenticated: true });
  if (!draft || draft.published_work_id) notFound();

  return (
    <div className="mx-auto flex w-full max-w-[1160px] flex-col gap-6 px-4 py-8 sm:px-6">
      <GoBackLink fallbackHref={draft.latest_job_id ? `/jobs/${draft.latest_job_id}` : '/create'}>
        {tCreate('backToPrevious')}
      </GoBackLink>
      <PageHeading eyebrow={t('eyebrow')} title={t('title')} />
      <PublishForm draft={draft} />
    </div>
  );
}

import { notFound } from 'next/navigation';
import { getTranslations } from 'next-intl/server';

import { PublishForm } from '@/components/publish/publish-form';
import { GoBackLink } from '@/components/ui/go-back-link';
import { PageHeading } from '@/components/ui/primitives';
import { redirect } from '@/i18n/navigation';
import { serverFetchOrNull } from '@/lib/api/server';
import type { Draft } from '@/lib/api/types';
import { imageCreationStudioHref, isImageCreationOperation } from '@/lib/image-draft';
import { isVideoCreationOperation, videoCreationStudioHref } from '@/lib/video-draft';

function publishBackHref(draft: Draft): string {
  const operation = draft.params?.operation;
  if (isImageCreationOperation(operation)) return imageCreationStudioHref(draft.id);
  if (isVideoCreationOperation(operation)) return videoCreationStudioHref(draft.id);
  if (draft.latest_job_id) return `/jobs/${draft.latest_job_id}`;
  return '/create';
}

interface Params {
  params: Promise<{ locale: string; draftId: string }>;
}

export async function generateMetadata() {
  const t = await getTranslations('publishPage');
  return { title: t('title') };
}

export default async function PublishPage({ params }: Params) {
  const { locale, draftId } = await params;
  const t = await getTranslations('publishPage');
  const tCreate = await getTranslations('createPage');

  const draft = await serverFetchOrNull<Draft>(`/v1/drafts/${draftId}`, { authenticated: true });
  if (!draft) notFound();
  // Once published there is nothing left to fill in here — the work itself,
  // not a 404, is what "找不到发布表单" should land on.
  if (draft.published_work_id) redirect({ href: `/work/${draft.published_work_id}`, locale });

  return (
    <div className="mx-auto flex w-full max-w-[1160px] flex-col gap-6 px-4 py-8 sm:px-6">
      <GoBackLink fallbackHref={publishBackHref(draft)}>
        {tCreate('backToPrevious')}
      </GoBackLink>
      <PageHeading eyebrow={t('eyebrow')} title={t('title')} />
      <PublishForm draft={draft} />
    </div>
  );
}

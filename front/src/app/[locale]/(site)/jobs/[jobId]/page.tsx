import { notFound } from 'next/navigation';
import { getTranslations } from 'next-intl/server';

import { JobProgress } from '@/components/job/job-progress';
import { PageHeading } from '@/components/ui/primitives';
import { serverFetchOrNull } from '@/lib/api/server';
import type { GenerationJob } from '@/lib/api/types';

interface Params {
  params: Promise<{ jobId: string }>;
}

export async function generateMetadata() {
  const t = await getTranslations('jobPage');
  return { title: t('title') };
}

export default async function JobPage({ params }: Params) {
  const { jobId } = await params;
  const t = await getTranslations('jobPage');

  // Rendered server-side first so a reload of a finished job shows the result
  // immediately, without waiting for a stream that has nothing left to send.
  const job = await serverFetchOrNull<GenerationJob>(`/v1/generation-jobs/${jobId}`, {
    authenticated: true,
  });
  if (!job) notFound();

  return (
    <div className="mx-auto flex w-full max-w-[1160px] flex-col gap-6 px-4 py-6 sm:px-6">
      <PageHeading title={t('title')} description={t('subtitle', { id: job.id })} />
      <JobProgress jobId={jobId} initial={job} />
    </div>
  );
}

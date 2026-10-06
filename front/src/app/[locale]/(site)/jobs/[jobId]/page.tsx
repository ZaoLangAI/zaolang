import { notFound } from 'next/navigation';
import { getTranslations } from 'next-intl/server';

import { JobProgress } from '@/components/job/job-progress';
import { BackLink } from '@/components/ui/back-link';
import { redirect } from '@/i18n/navigation';
import { serverFetchOrNull } from '@/lib/api/server';
import type { GenerationJob } from '@/lib/api/types';
import { assetWorkspaceHref, isImageOperation } from '@/lib/asset-job-href';
import { isVideoCreationOperation, videoCreationStudioHref } from '@/lib/video-draft';

interface Params {
  params: Promise<{ locale: string; jobId: string }>;
}

export async function generateMetadata() {
  const t = await getTranslations('jobPage');
  return { title: t('title') };
}

function resumeHrefForJob(job: GenerationJob): string | null {
  // An asset image lives in its card's workspace. A general / cover image
  // (the retired image studio, the canvas Agent) stays here, read-only.
  if (isImageOperation(job.operation)) return assetWorkspaceHref(job);
  if (job.draft_id && isVideoCreationOperation(job.operation)) {
    return videoCreationStudioHref(job.draft_id, job.id);
  }
  return null;
}

export default async function JobPage({ params }: Params) {
  const { locale, jobId } = await params;
  const t = await getTranslations('jobPage');

  // Rendered server-side first so a reload of a finished job shows the result
  // immediately, without waiting for a stream that has nothing left to send.
  const job = await serverFetchOrNull<GenerationJob>(`/v1/generation-jobs/${jobId}`, {
    authenticated: true,
  });
  if (!job) notFound();

  // Video creation and asset images have no standalone progress page — old
  // bookmarks and leftover links land back in the studio / workspace.
  const resumeHref = resumeHrefForJob(job);
  if (resumeHref) redirect({ href: resumeHref, locale });

  return (
    <div className="mx-auto flex w-full max-w-[1160px] flex-col gap-6 px-4 py-6 sm:px-6">
      <BackLink href="/create">{t('backToCreate')}</BackLink>
      <JobProgress jobId={jobId} initial={job} />
    </div>
  );
}

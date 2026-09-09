import { getTranslations } from 'next-intl/server';

import { GoBackLink } from '@/components/ui/go-back-link';
import { EmptyState, PageHeading } from '@/components/ui/primitives';
import { ScriptClipStudio } from '@/features/script/script-clip-studio';
import type { ScriptDetail } from '@/features/script/api';
import {
  locateBreakpoint,
  parseBreakpointQueryKey,
  parseScriptDraftId,
  parseScriptEpisodeId,
} from '@/features/script/script-breakpoint';
import { serverFetchOrNull } from '@/lib/api/server';
import type { Draft } from '@/lib/api/types';

export async function generateMetadata() {
  const t = await getTranslations('scriptStudio');
  return { title: t('clipTitle'), description: t('clipSubtitle') };
}

export default async function ScriptClipPage({
  params,
  searchParams,
}: {
  params: Promise<{ episodeId: string }>;
  searchParams: Promise<{ key?: string; draftId?: string }>;
}) {
  const t = await getTranslations('scriptStudio');
  const tActions = await getTranslations('actions');
  const { episodeId: rawEpisodeId } = await params;
  const { key: rawKey, draftId: rawDraftId } = await searchParams;
  const episodeId = parseScriptEpisodeId(rawEpisodeId);
  const key = parseBreakpointQueryKey(rawKey);
  const draftId = parseScriptDraftId(rawDraftId);
  const backHref = episodeId ? `/create/script/${episodeId}` : '/create/script';

  if (!episodeId || !key) {
    return (
      <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-6 px-4 py-8 sm:px-6">
        <GoBackLink fallbackHref={backHref}>{tActions('back')}</GoBackLink>
        <EmptyState title={t('clipInvalid')} description={t('clipMissingHint')} />
      </div>
    );
  }

  const script = await serverFetchOrNull<ScriptDetail>(`/v1/scripts/${episodeId}`, {
    authenticated: true,
  });
  if (!script || !locateBreakpoint(script.script, key)) {
    return (
      <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-6 px-4 py-8 sm:px-6">
        <GoBackLink fallbackHref={backHref}>{tActions('back')}</GoBackLink>
        <EmptyState title={t('clipMissing')} description={t('clipMissingHint')} />
      </div>
    );
  }

  const initialDraft = draftId
    ? ((await serverFetchOrNull<Draft>(`/v1/drafts/${draftId}`, { authenticated: true })) ??
      undefined)
    : undefined;

  return (
    <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-6 px-4 py-6 sm:px-6">
      <GoBackLink fallbackHref={backHref}>{t('clipBackToScript')}</GoBackLink>
      <PageHeading title={t('clipTitle')} description={t('clipSubtitle')} />
      <ScriptClipStudio
        episodeId={episodeId}
        breakpointKey={key}
        script={script}
        initialDraft={initialDraft}
      />
    </div>
  );
}

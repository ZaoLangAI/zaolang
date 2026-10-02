import { getTranslations } from 'next-intl/server';

import { GoBackLink } from '@/components/ui/go-back-link';
import { EmptyState } from '@/components/ui/primitives';
import { BlockingStudio } from '@/features/blocking/blocking-studio';
import type { ScriptDetail } from '@/features/script/api';
import { parseScriptEpisodeId } from '@/features/script/script-breakpoint';
import { serverFetchOrNull } from '@/lib/api/server';

export async function generateMetadata() {
  const t = await getTranslations('blockingStudio');
  return { title: t('title'), description: t('subtitle') };
}

export default async function BlockingStudioPage({
  params,
}: {
  params: Promise<{ episodeId: string }>;
}) {
  const t = await getTranslations('blockingStudio');
  const { episodeId: rawEpisodeId } = await params;
  const episodeId = parseScriptEpisodeId(rawEpisodeId);
  const backHref = episodeId ? `/create/script/${episodeId}` : '/create/script';
  const detail = episodeId
    ? await serverFetchOrNull<ScriptDetail>(`/v1/scripts/${episodeId}`, { authenticated: true })
    : null;

  // `blocking` is `null` whenever `blocking_studio_enabled` is off for this
  // user — the same "off means hidden" contract as the API's 404s.
  const unavailable = !episodeId || !detail || !detail.blocking;
  const noScript = !unavailable && detail.turns.length === 0;

  const title = detail?.title ? t('titleWithScript', { title: detail.title }) : t('title');
  return (
    // Desktop: exactly one screen under the 4rem top bar, so the viewport and
    // the side panel get all the height; phones scroll a stacked layout.
    <div className="mx-auto flex w-full max-w-[1920px] flex-col gap-2 px-3 py-2 sm:px-4 lg:h-[calc(100dvh-4rem-1px)] lg:py-3">
      <div className="flex min-w-0 shrink-0 items-center gap-3">
        <GoBackLink fallbackHref={backHref}>{t('backToScript')}</GoBackLink>
        <h1 className="min-w-0 truncate text-base font-semibold text-text sm:text-lg">{title}</h1>
      </div>
      {unavailable ? (
        <EmptyState title={t('unavailableTitle')} description={t('unavailableHint')} />
      ) : noScript ? (
        <EmptyState title={t('noScriptTitle')} description={t('noScriptHint')} />
      ) : (
        <BlockingStudio episodeId={episodeId} initial={detail} />
      )}
    </div>
  );
}

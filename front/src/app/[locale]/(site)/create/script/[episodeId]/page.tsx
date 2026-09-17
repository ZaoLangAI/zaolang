import { getTranslations } from 'next-intl/server';

import { GoBackLink } from '@/components/ui/go-back-link';
import { PageHeading } from '@/components/ui/primitives';
import { ScriptEditor } from '@/features/script/script-editor';

function toLinkKind(raw: string | undefined): 'character' | 'scene' | undefined {
  return raw === 'character' || raw === 'scene' ? raw : undefined;
}

export async function generateMetadata() {
  const t = await getTranslations('scriptStudio');
  return { title: t('title'), description: t('subtitle') };
}

export default async function ScriptEditorPage({
  params,
  searchParams,
}: {
  params: Promise<{ episodeId: string }>;
  // Set only on the "返回文案创作" jump-back from the image studio
  // (`InlineImageResult`) — see `ScriptEditor`'s own `pendingLink` prop for
  // how these get consumed (auto-relink, then stripped from the URL).
  searchParams: Promise<{ linkKind?: string; linkLabel?: string; linkRefId?: string }>;
}) {
  const t = await getTranslations('scriptStudio');
  const tActions = await getTranslations('actions');
  const { episodeId } = await params;
  const { linkKind, linkLabel, linkRefId } = await searchParams;
  const resolvedLinkKind = toLinkKind(linkKind);
  const pendingLink =
    resolvedLinkKind && linkLabel && linkRefId
      ? { kind: resolvedLinkKind, label: linkLabel, refId: linkRefId }
      : undefined;
  return (
    <div className="mx-auto flex w-full max-w-[1280px] flex-col gap-6 px-4 py-8 sm:px-6">
      <GoBackLink fallbackHref="/create/script">{tActions('back')}</GoBackLink>
      <PageHeading title={t('title')} />
      <ScriptEditor episodeId={episodeId} pendingLink={pendingLink} />
    </div>
  );
}

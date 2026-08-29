'use client';

import dynamic from 'next/dynamic';

import { StudioSkeleton } from '@/components/studio/studio-skeleton';
import type { Draft, StyleGalleryEntry, WorkDetail } from '@/lib/api/types';

const ImageGenerationStudio = dynamic(
  () =>
    import('@/components/studio/image-generation-studio').then((mod) => mod.ImageGenerationStudio),
  { loading: () => <StudioSkeleton /> },
);

const VideoGenerationStudio = dynamic(
  () =>
    import('@/components/studio/video-generation-studio').then((mod) => mod.VideoGenerationStudio),
  { loading: () => <StudioSkeleton /> },
);

const AudioGenerationStudio = dynamic(
  () =>
    import('@/components/studio/audio-generation-studio').then((mod) => mod.AudioGenerationStudio),
  { loading: () => <StudioSkeleton /> },
);

type ImageAssetKind = 'general' | 'character' | 'scene' | 'cover';
type VideoAssetKind = 'general' | 'character_action' | 'transition_video' | 'cover_video';
type LinkKind = 'character' | 'scene';

/**
 * Loads exactly one generation studio chunk for `/create/new`.
 *
 * Declaring all three `next/dynamic` factories in this module keeps the RSC
 * page free of static studio imports; only the branch that mounts actually
 * fetches its chunk.
 */
export function CreateStudio({
  operation,
  initialPrompt,
  reference,
  initialDraft,
  style,
  initialAssetKind,
  initialVideoAssetKind,
  initialTargetCharacterId,
  initialTargetSceneId,
  subjectNameHint,
  returnTo,
  returnLinkKind,
  returnLinkLabel,
  initialReferenceCharacterIds,
  initialReferenceSceneIds,
  linkEpisodeId,
  linkBreakpointKey,
}: {
  operation: 'text_to_image' | 'text_to_video' | 'audio_generation';
  initialPrompt?: string;
  reference?: WorkDetail;
  initialDraft?: Draft;
  style?: StyleGalleryEntry | null;
  initialAssetKind?: ImageAssetKind;
  initialVideoAssetKind?: VideoAssetKind;
  initialTargetCharacterId?: string;
  initialTargetSceneId?: string;
  subjectNameHint?: string;
  returnTo?: string;
  returnLinkKind?: LinkKind;
  returnLinkLabel?: string;
  initialReferenceCharacterIds?: string[];
  initialReferenceSceneIds?: string[];
  linkEpisodeId?: string;
  linkBreakpointKey?: string;
}) {
  if (operation === 'audio_generation') {
    return <AudioGenerationStudio initialPrompt={initialPrompt} reference={reference} />;
  }
  if (operation === 'text_to_image') {
    return (
      <ImageGenerationStudio
        initialPrompt={initialPrompt}
        reference={reference}
        initialDraft={initialDraft}
        initialAssetKind={initialAssetKind}
        initialTargetCharacterId={initialTargetCharacterId}
        initialTargetSceneId={initialTargetSceneId}
        subjectNameHint={subjectNameHint}
        returnTo={returnTo}
        returnLinkKind={returnLinkKind}
        returnLinkLabel={returnLinkLabel}
        linkEpisodeId={linkEpisodeId}
      />
    );
  }
  return (
    <VideoGenerationStudio
      operation={operation}
      initialPrompt={initialPrompt}
      reference={reference}
      initialDraft={initialDraft}
      initialStyleParams={style?.params}
      initialStyleGalleryId={style?.id}
      initialVideoAssetKind={initialVideoAssetKind}
      initialTargetCharacterId={initialTargetCharacterId}
      subjectNameHint={subjectNameHint}
      initialReferenceCharacterIds={initialReferenceCharacterIds}
      initialReferenceSceneIds={initialReferenceSceneIds}
      linkEpisodeId={linkEpisodeId}
      linkBreakpointKey={linkBreakpointKey}
    />
  );
}

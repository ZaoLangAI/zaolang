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

const MusicGenerationStudio = dynamic(
  () =>
    import('@/components/studio/music-generation-studio').then((mod) => mod.MusicGenerationStudio),
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
  initialJobId,
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
  continuitySourceAssetId,
  initialSkillId,
  initialReferenceAssetIds,
}: {
  operation: 'text_to_image' | 'text_to_video' | 'audio_generation' | 'music_generation';
  initialPrompt?: string;
  reference?: WorkDetail;
  initialDraft?: Draft;
  /** Notification click-through — which job under `initialDraft` to show. */
  initialJobId?: string;
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
  /** The previous script breakpoint's already-generated video, if any — see
   * `VideoGenerationStudio`'s own doc comment. */
  continuitySourceAssetId?: string;
  initialSkillId?: string;
  /** Reference images handed over by a deep link — the canvas turns an edge
   * from a picture card into this. */
  initialReferenceAssetIds?: string[];
}) {
  if (operation === 'audio_generation') {
    return <AudioGenerationStudio initialPrompt={initialPrompt} reference={reference} />;
  }
  if (operation === 'music_generation') {
    return <MusicGenerationStudio initialPrompt={initialPrompt} />;
  }
  if (operation === 'text_to_image') {
    return (
      <ImageGenerationStudio
        initialPrompt={initialPrompt}
        reference={reference}
        initialDraft={initialDraft}
        initialJobId={initialJobId}
        initialAssetKind={initialAssetKind}
        initialTargetCharacterId={initialTargetCharacterId}
        initialTargetSceneId={initialTargetSceneId}
        subjectNameHint={subjectNameHint}
        returnTo={returnTo}
        returnLinkKind={returnLinkKind}
        returnLinkLabel={returnLinkLabel}
        linkEpisodeId={linkEpisodeId}
        initialSkillId={initialSkillId}
        initialReferenceAssetIds={initialReferenceAssetIds}
      />
    );
  }
  return (
    <VideoGenerationStudio
      operation={operation}
      initialPrompt={initialPrompt}
      reference={reference}
      initialDraft={initialDraft}
      initialJobId={initialJobId}
      initialStyleParams={style?.params}
      initialStyleGalleryId={style?.id}
      initialVideoAssetKind={initialVideoAssetKind}
      initialTargetCharacterId={initialTargetCharacterId}
      subjectNameHint={subjectNameHint}
      initialReferenceCharacterIds={initialReferenceCharacterIds}
      initialReferenceSceneIds={initialReferenceSceneIds}
      linkEpisodeId={linkEpisodeId}
      linkBreakpointKey={linkBreakpointKey}
      continuitySourceAssetId={continuitySourceAssetId}
      initialSkillId={initialSkillId}
    />
  );
}

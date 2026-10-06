'use client';

import dynamic from 'next/dynamic';

import { StudioSkeleton } from '@/components/studio/studio-skeleton';
import type { Draft, StyleGalleryEntry, WorkDetail } from '@/lib/api/types';

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

type VideoAssetKind = 'general' | 'character_action' | 'transition_video' | 'cover_video';

/**
 * Loads exactly one generation studio chunk for `/create/new`.
 *
 * Declaring every `next/dynamic` factory in this module keeps the RSC
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
  initialVideoAssetKind,
  initialTargetCharacterId,
  subjectNameHint,
  initialReferenceCharacterIds,
  initialReferenceSceneIds,
  initialReferencePropIds,
  linkEpisodeId,
  linkBreakpointKey,
  continuitySourceAssetId,
  initialSkillId,
}: {
  operation: 'text_to_video' | 'audio_generation' | 'music_generation';
  initialPrompt?: string;
  reference?: WorkDetail;
  initialDraft?: Draft;
  /** Notification click-through — which job under `initialDraft` to show. */
  initialJobId?: string;
  style?: StyleGalleryEntry | null;
  initialVideoAssetKind?: VideoAssetKind;
  initialTargetCharacterId?: string;
  subjectNameHint?: string;
  initialReferenceCharacterIds?: string[];
  initialReferenceSceneIds?: string[];
  initialReferencePropIds?: string[];
  linkEpisodeId?: string;
  linkBreakpointKey?: string;
  /** The previous script breakpoint's already-generated video, if any — see
   * `VideoGenerationStudio`'s own doc comment. */
  continuitySourceAssetId?: string;
  initialSkillId?: string;
}) {
  if (operation === 'audio_generation') {
    return <AudioGenerationStudio initialPrompt={initialPrompt} reference={reference} />;
  }
  if (operation === 'music_generation') {
    return <MusicGenerationStudio initialPrompt={initialPrompt} />;
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
      initialReferencePropIds={initialReferencePropIds}
      linkEpisodeId={linkEpisodeId}
      linkBreakpointKey={linkBreakpointKey}
      continuitySourceAssetId={continuitySourceAssetId}
      initialSkillId={initialSkillId}
    />
  );
}

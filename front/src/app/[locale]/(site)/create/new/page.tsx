import { getTranslations } from 'next-intl/server';

import { AudioGenerationStudio } from '@/components/studio/audio-generation-studio';
import { ImageGenerationStudio } from '@/components/studio/image-generation-studio';
import { VideoGenerationStudio } from '@/components/studio/video-generation-studio';
import { BackLink } from '@/components/ui/back-link';
import { GoBackLink } from '@/components/ui/go-back-link';
import { PageHeading } from '@/components/ui/primitives';
import { serverFetchOrNull } from '@/lib/api/server';
import type { Draft, StyleGalleryEntry, WorkDetail } from '@/lib/api/types';

// `image_creation`/`video_creation` are URL-level modes only — the merged
// "图片创作"/"视频创作" cards from `create-mode-cards.tsx` — not backend
// `Operation`s. `image_creation` always starts the studio on `text_to_image`;
// `video_creation` always starts it on `text_to_video`. Each studio derives
// the actual operation itself the moment a reference is attached
// (`ImageGenerationStudio`'s `text_to_image → image_to_image`,
// `VideoGenerationStudio`'s `text_to_video → image_to_video/video_to_video`
// — the same "derive from what's attached" pattern on both sides).
const MODES = ['image_creation', 'video_creation', 'audio_generation'] as const;
type Mode = (typeof MODES)[number];

const OPERATION_BY_MODE: Record<Mode, 'text_to_image' | 'text_to_video' | 'audio_generation'> = {
  image_creation: 'text_to_image',
  video_creation: 'text_to_video',
  audio_generation: 'audio_generation',
};

const TITLE_KEYS: Record<Mode, string> = {
  image_creation: 'modeImageCreationTitle',
  video_creation: 'modeVideoCreationTitle',
  audio_generation: 'modeAudioGenerationTitle',
};

const DESCRIPTION_KEYS: Record<Mode, string> = {
  image_creation: 'modeImageCreationDesc',
  video_creation: 'modeVideoCreationDesc',
  audio_generation: 'modeAudioGenerationDesc',
};

const PROMPT_MAX_LENGTH = 600;

// `ImageGenerationStudio`'s own asset-kind union — validated here rather
// than trusted blindly from the query string.
const ASSET_KINDS = ['general', 'character', 'scene', 'cover'] as const;
type AssetKind = (typeof ASSET_KINDS)[number];
// `VideoGenerationStudio`'s asset-kind union — mirrors the backend
// `VideoAssetKind` enum (see `zaolang-generation-jobs`).
const VIDEO_ASSET_KINDS = [
  'general',
  'character_action',
  'transition_video',
  'cover_video',
] as const;
type VideoAssetKind = (typeof VIDEO_ASSET_KINDS)[number];
const LINK_KINDS = ['character', 'scene'] as const;
type LinkKind = (typeof LINK_KINDS)[number];

// The script studio's "生成角色图/场景图" jump-out is the only caller of
// this deep link today, and it only ever points back at one route shape —
// keeping the whitelist this narrow (rather than "any same-origin path")
// is what rules out an open redirect without needing a full URL parse.
function sanitizeReturnTo(raw: string | undefined): string | undefined {
  if (!raw || !raw.startsWith('/create/script/')) return undefined;
  return raw;
}

// Comma-joined id list from the script studio's "建议切分" video jump-out
// (`buildBreakpointVideoHref`) — capped to match `GenerationParams.character_ids`/
// `scene_ids`'s own `max_length=4` so the studio never even offers more than
// the backend would accept.
function parseReferenceIds(raw: string | undefined): string[] | undefined {
  if (!raw) return undefined;
  const ids = raw
    .split(',')
    .map((id) => id.trim())
    .filter(Boolean)
    .slice(0, 4);
  return ids.length > 0 ? ids : undefined;
}

export async function generateMetadata() {
  const t = await getTranslations('createPage');
  return { title: t('startCreating') };
}

export default async function NewCreationPage({
  searchParams,
}: {
  searchParams: Promise<{
    mode?: string;
    prompt?: string;
    ref?: string;
    styleId?: string;
    draftId?: string;
    assetKind?: string;
    videoAssetKind?: string;
    targetCharacterId?: string;
    targetSceneId?: string;
    subjectNameHint?: string;
    returnTo?: string;
    returnLinkKind?: string;
    returnLinkLabel?: string;
    referenceCharacterIds?: string;
    referenceSceneIds?: string;
    linkEpisodeId?: string;
  }>;
}) {
  const {
    mode,
    prompt,
    ref,
    styleId,
    draftId,
    assetKind,
    videoAssetKind,
    targetCharacterId,
    targetSceneId,
    subjectNameHint,
    returnTo,
    returnLinkKind,
    returnLinkLabel,
    referenceCharacterIds,
    referenceSceneIds,
    linkEpisodeId,
  } = await searchParams;
  const t = await getTranslations('createPage');

  const resolvedMode: Mode = MODES.includes(mode as Mode) ? (mode as Mode) : 'video_creation';
  const operation = OPERATION_BY_MODE[resolvedMode];
  const title = t(TITLE_KEYS[resolvedMode]);
  const description = t(DESCRIPTION_KEYS[resolvedMode]);

  // `ref` is inspiration, not a remix source: it seeds the prompt and shows the
  // work the idea came from, but it never becomes `source_work_id`. Remixing
  // still has to go through `/remix/[workId]`, which checks the authorisation.
  const reference = ref ? await serverFetchOrNull<WorkDetail>(`/v1/works/${ref}`) : null;

  // `styleId` comes from the style gallery — either the studio's own picker
  // dialog or the create page's inspiration wall, which link here with the
  // same query param instead of duplicating the apply logic server-side.
  const style = styleId
    ? await serverFetchOrNull<StyleGalleryEntry>(`/v1/style-gallery/${styleId}`)
    : null;

  // `draftId` resumes an image-creation session — its full version history
  // and latest output (see `GenerationVersionHistory`) — only meaningful for
  // `text_to_image`; audio still only ever lands on `/jobs/[jobId]`. Video
  // resumes too, but only as *material* for a fresh `video_to_video` draft
  // (`VideoGenerationStudio`'s `initialDraft` — no version history there).
  const initialDraft =
    draftId && (operation === 'text_to_image' || operation === 'text_to_video')
      ? ((await serverFetchOrNull<Draft>(`/v1/drafts/${draftId}`, { authenticated: true })) ??
        undefined)
      : undefined;

  // Only meaningful for the image studio (the script studio's jump-out
  // always starts one of those) — validated and defaulted here so the
  // component itself never has to distrust its own props.
  const sanitizedReturnTo = sanitizeReturnTo(returnTo);
  const resolvedAssetKind: AssetKind | undefined = ASSET_KINDS.includes(assetKind as AssetKind)
    ? (assetKind as AssetKind)
    : undefined;
  // Meaningful for the video studio — the character library's "生成动作
  // 视频" button deep-links here the same way the script studio's image
  // jump-out does for `assetKind` above.
  const resolvedVideoAssetKind: VideoAssetKind | undefined = VIDEO_ASSET_KINDS.includes(
    videoAssetKind as VideoAssetKind,
  )
    ? (videoAssetKind as VideoAssetKind)
    : undefined;
  const resolvedReturnLinkKind: LinkKind | undefined = LINK_KINDS.includes(
    returnLinkKind as LinkKind,
  )
    ? (returnLinkKind as LinkKind)
    : undefined;
  const resolvedReferenceCharacterIds = parseReferenceIds(referenceCharacterIds);
  const resolvedReferenceSceneIds = parseReferenceIds(referenceSceneIds);

  return (
    <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-6 px-4 py-6 sm:px-6">
      {resolvedMode === 'image_creation' || resolvedMode === 'video_creation' ? (
        <GoBackLink fallbackHref="/create">{t('backToPrevious')}</GoBackLink>
      ) : (
        <BackLink href="/create">{t('backToCreate')}</BackLink>
      )}
      <PageHeading eyebrow={t('eyebrow')} title={title} description={description} />
      {operation === 'audio_generation' ? (
        <AudioGenerationStudio
          initialPrompt={prompt?.trim().slice(0, PROMPT_MAX_LENGTH)}
          reference={reference ?? undefined}
        />
      ) : operation === 'text_to_image' ? (
        <ImageGenerationStudio
          initialPrompt={prompt?.trim().slice(0, PROMPT_MAX_LENGTH)}
          reference={reference ?? undefined}
          initialDraft={initialDraft}
          initialAssetKind={resolvedAssetKind}
          initialTargetCharacterId={targetCharacterId}
          initialTargetSceneId={targetSceneId}
          subjectNameHint={subjectNameHint?.trim().slice(0, 60) || undefined}
          returnTo={sanitizedReturnTo}
          returnLinkKind={resolvedReturnLinkKind}
          returnLinkLabel={returnLinkLabel?.trim().slice(0, 60) || undefined}
          linkEpisodeId={linkEpisodeId}
        />
      ) : (
        <VideoGenerationStudio
          operation={operation}
          initialPrompt={prompt?.trim().slice(0, PROMPT_MAX_LENGTH)}
          reference={reference ?? undefined}
          initialDraft={initialDraft}
          initialStyleParams={style?.params}
          initialStyleGalleryId={style?.id}
          initialVideoAssetKind={resolvedVideoAssetKind}
          initialTargetCharacterId={targetCharacterId}
          subjectNameHint={subjectNameHint?.trim().slice(0, 60) || undefined}
          initialReferenceCharacterIds={resolvedReferenceCharacterIds}
          initialReferenceSceneIds={resolvedReferenceSceneIds}
          linkEpisodeId={linkEpisodeId}
        />
      )}
    </div>
  );
}

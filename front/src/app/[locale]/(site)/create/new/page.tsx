import { getTranslations } from 'next-intl/server';

import { CreateStudio } from '@/components/studio/create-studio';
import { BackLink } from '@/components/ui/back-link';
import { GoBackLink } from '@/components/ui/go-back-link';
import { PageHeading } from '@/components/ui/primitives';
import { serverFetchOrNull } from '@/lib/api/server';
import type { Draft, StyleGalleryEntry, WorkDetail } from '@/lib/api/types';
import { STUDIO_PROMPT_MAX_LENGTH } from '@/lib/prompt-limits';
import { readDraftReturnContext, sanitizeReturnTo, studioSessionKey } from '@/lib/studio-session';
import { isSceneLighting, isSceneWeather } from '@/features/image-assets/vocabulary';

// `image_creation`/`video_creation` are URL-level modes only — the merged
// "图片创作"/"视频创作" cards from `create-mode-cards.tsx` — not backend
// `Operation`s. `image_creation` always starts the studio on `text_to_image`;
// `video_creation` always starts it on `text_to_video`. Each studio derives
// the actual operation itself the moment a reference is attached
// (`ImageGenerationStudio`'s `text_to_image → image_to_image`,
// `VideoGenerationStudio`'s `text_to_video → image_to_video/video_to_video`
// — the same "derive from what's attached" pattern on both sides).
const MODES = ['image_creation', 'video_creation', 'audio_generation', 'music_generation'] as const;
type Mode = (typeof MODES)[number];

const OPERATION_BY_MODE: Record<
  Mode,
  'text_to_image' | 'text_to_video' | 'audio_generation' | 'music_generation'
> = {
  image_creation: 'text_to_image',
  video_creation: 'text_to_video',
  audio_generation: 'audio_generation',
  music_generation: 'music_generation',
};

const TITLE_KEYS: Record<Mode, string> = {
  image_creation: 'modeImageCreationTitle',
  video_creation: 'modeVideoCreationTitle',
  audio_generation: 'modeAudioGenerationTitle',
  music_generation: 'modeMusicGenerationTitle',
};

const DESCRIPTION_KEYS: Record<Mode, string> = {
  image_creation: 'modeImageCreationDesc',
  video_creation: 'modeVideoCreationDesc',
  audio_generation: 'modeAudioGenerationDesc',
  music_generation: 'modeMusicGenerationDesc',
};

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

// Comma-joined id list from the script studio's "建议切分" video jump-out
// (`buildBreakpointVideoHref`) — capped to match `GenerationParams.character_ids`/
// `scene_ids`'s own `max_length=4` so the studio never even offers more than
// the backend would accept.
// `GenerationJob.id` is `job_` + a 26-char Crockford token (`new_id`),
// stored in a `String(40)` column — reject anything else so a crafted
// query string cannot be forwarded into `GET /v1/generation-jobs/{id}`.
function parseJobId(raw: string | undefined): string | undefined {
  if (!raw || raw.length > 40 || !/^job_[0-9A-Za-z]+$/.test(raw)) return undefined;
  return raw;
}

function parseReferenceIds(raw: string | undefined): string[] | undefined {
  if (!raw) return undefined;
  const ids = raw
    .split(',')
    .map((id) => id.trim())
    .filter(Boolean)
    .slice(0, 4);
  return ids.length > 0 ? ids : undefined;
}

/** Same strictness as `parseAssetId`, for the comma-separated list the canvas
 * sends: every entry must look like a real asset id before it is forwarded
 * into `GET /v1/assets/{id}`. */
function parseAssetIds(raw: string | undefined): string[] | undefined {
  if (!raw) return undefined;
  const ids = raw
    .split(',')
    .map((id) => id.trim())
    .filter((id) => id.length <= 40 && /^ast_[0-9A-Za-z]+$/.test(id))
    .slice(0, 4);
  return ids.length > 0 ? ids : undefined;
}

// `Asset.id` is `ast_` + a Crockford token (`new_id`), stored in a
// `String(40)` column — same reject-anything-else stance as `parseJobId`,
// so a crafted `continuityAssetId` can't be forwarded into
// `POST /v1/assets/{id}/frame` as anything other than a well-formed id.
function parseAssetId(raw: string | undefined): string | undefined {
  if (!raw || raw.length > 40 || !/^ast_[0-9A-Za-z]+$/.test(raw)) return undefined;
  return raw;
}

// `CreationSkill.id` is `sk_` + a 26-char Crockford token (`new_id`),
// stored in a `String(40)` column — same reject-anything-else stance as
// `parseJobId`, so a crafted `skillId` cannot be forwarded into
// `POST /v1/skills/{id}/apply`.
function parseSkillId(raw: string | undefined): string | undefined {
  if (!raw || raw.length > 40 || !/^sk_[0-9A-Za-z]+$/.test(raw)) return undefined;
  return raw;
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
    linkBreakpointKey?: string;
    referenceAssetIds?: string;
    continuityAssetId?: string;
    jobId?: string;
    skillId?: string;
    sceneLighting?: string;
    sceneWeather?: string;
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
    linkBreakpointKey,
    referenceAssetIds,
    continuityAssetId,
    jobId,
    skillId,
    sceneLighting,
    sceneWeather,
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

  // `draftId` resumes a creation session — its full version history and
  // latest output (see `GenerationVersionHistory`) — for `text_to_image` and
  // (now) `text_to_video` alike; audio still only ever lands on
  // `/jobs/[jobId]`. `image_to_video`/`video_to_video` sessions (remix,
  // "最近草稿" edit) never carry a `draftId` in the URL, so this only ever
  // resolves for a plain `text_to_video` mode session.
  const initialDraft =
    draftId && (operation === 'text_to_image' || operation === 'text_to_video')
      ? ((await serverFetchOrNull<Draft>(`/v1/drafts/${draftId}`, { authenticated: true })) ??
        undefined)
      : undefined;

  // A notification click is `?draftId=&jobId=`; draft cards are
  // `?draftId=` only and resume `latest_job_id`. The jump-out trio is
  // restored from the draft when the URL does not carry it (see
  // `draftReturnParams`). `jobId` is validated here so the studio never
  // has to distrust a raw query string.
  const resolvedJobId = parseJobId(jobId);

  // Only meaningful for the image studio (the script studio's jump-out
  // always starts one of those) — validated and defaulted here so the
  // component itself never has to distrust its own props.
  const draftReturn = readDraftReturnContext(initialDraft?.params);
  const sanitizedReturnTo = sanitizeReturnTo(returnTo) ?? draftReturn.returnTo;
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
    : draftReturn.returnLinkKind;
  const resolvedReturnLinkLabel =
    returnLinkLabel?.trim().slice(0, 60) || draftReturn.returnLinkLabel;
  const resolvedReferenceCharacterIds = parseReferenceIds(referenceCharacterIds);
  const resolvedReferenceSceneIds = parseReferenceIds(referenceSceneIds);
  const resolvedReferenceAssetIds = parseAssetIds(referenceAssetIds);
  // The previous script breakpoint's video, if any — see
  // `previousBoundVideoAssetId`/`buildBreakpointVideoHref`. Only meaningful
  // without an existing `draftId` (a resumed session already has its own
  // material); the studio itself re-derives that condition too.
  const resolvedContinuityAssetId = parseAssetId(continuityAssetId);
  const resolvedSkillId = parseSkillId(skillId);
  // The script studio's scene jump-out reads 日/夜 (and 雨/雪) off the
  // heading (`parseScenePresets`); validated against the generated unions.
  const initialScenePresets = {
    lighting: isSceneLighting(sceneLighting) ? sceneLighting : undefined,
    weather: isSceneWeather(sceneWeather) ? sceneWeather : undefined,
  };

  return (
    <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-6 px-4 py-6 sm:px-6">
      {resolvedMode === 'image_creation' || resolvedMode === 'video_creation' ? (
        <GoBackLink fallbackHref="/create">{t('backToPrevious')}</GoBackLink>
      ) : (
        <BackLink href="/create">{t('backToCreate')}</BackLink>
      )}
      <PageHeading eyebrow={t('eyebrow')} title={title} description={description} />
      <CreateStudio
        key={studioSessionKey({
          draftId: initialDraft?.id ?? draftId,
          jobId: resolvedJobId,
          mode: resolvedMode,
          assetKind: resolvedAssetKind,
          videoAssetKind: resolvedVideoAssetKind,
          targetCharacterId,
          targetSceneId,
          subjectNameHint: subjectNameHint?.trim().slice(0, 60),
          linkBreakpointKey,
          continuitySourceAssetId: resolvedContinuityAssetId,
          skillId: resolvedSkillId,
          scenePresets: [initialScenePresets.lighting, initialScenePresets.weather]
            .filter(Boolean)
            .join('+'),
        })}
        operation={operation}
        initialPrompt={prompt?.trim().slice(0, STUDIO_PROMPT_MAX_LENGTH)}
        reference={reference ?? undefined}
        initialDraft={initialDraft}
        initialJobId={resolvedJobId}
        style={style}
        initialAssetKind={resolvedAssetKind}
        initialVideoAssetKind={resolvedVideoAssetKind}
        initialTargetCharacterId={targetCharacterId}
        initialTargetSceneId={targetSceneId}
        subjectNameHint={subjectNameHint?.trim().slice(0, 60) || undefined}
        returnTo={sanitizedReturnTo}
        returnLinkKind={resolvedReturnLinkKind}
        returnLinkLabel={resolvedReturnLinkLabel}
        initialReferenceCharacterIds={resolvedReferenceCharacterIds}
        initialReferenceSceneIds={resolvedReferenceSceneIds}
        linkEpisodeId={linkEpisodeId}
        linkBreakpointKey={linkBreakpointKey}
        continuitySourceAssetId={resolvedContinuityAssetId}
        initialSkillId={resolvedSkillId}
        initialReferenceAssetIds={resolvedReferenceAssetIds}
        initialScenePresets={initialScenePresets}
      />
    </div>
  );
}

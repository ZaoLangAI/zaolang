import { getTranslations } from 'next-intl/server';

import { CreateStudio } from '@/components/studio/create-studio';
import { BackLink } from '@/components/ui/back-link';
import { GoBackLink } from '@/components/ui/go-back-link';
import { PageHeading } from '@/components/ui/primitives';
import { redirect } from '@/i18n/navigation';
import { serverFetchOrNull } from '@/lib/api/server';
import type { Draft, StyleGalleryEntry, WorkDetail } from '@/lib/api/types';
import { imageDraftHref } from '@/lib/asset-job-href';
import { STUDIO_PROMPT_MAX_LENGTH } from '@/lib/prompt-limits';
import { studioSessionKey } from '@/lib/studio-session';

// `video_creation` is a URL-level mode only — the "视频创作" card from
// `create-mode-cards.tsx` — not a backend `Operation`. It always starts the
// studio on `text_to_video`; `VideoGenerationStudio` derives
// `image_to_video`/`video_to_video` itself the moment a reference is
// attached. There is no image mode any more (AC-8): images are made in the
// card workspaces, and a leftover `?mode=image_creation` link is redirected.
const MODES = ['video_creation', 'audio_generation', 'music_generation'] as const;
type Mode = (typeof MODES)[number];

const OPERATION_BY_MODE: Record<Mode, 'text_to_video' | 'audio_generation' | 'music_generation'> = {
  video_creation: 'text_to_video',
  audio_generation: 'audio_generation',
  music_generation: 'music_generation',
};

const TITLE_KEYS: Record<Mode, string> = {
  video_creation: 'modeVideoCreationTitle',
  audio_generation: 'modeAudioGenerationTitle',
  music_generation: 'modeMusicGenerationTitle',
};

const DESCRIPTION_KEYS: Record<Mode, string> = {
  video_creation: 'modeVideoCreationDesc',
  audio_generation: 'modeAudioGenerationDesc',
  music_generation: 'modeMusicGenerationDesc',
};

// `VideoGenerationStudio`'s asset-kind union — mirrors the backend
// `VideoAssetKind` enum (see `zaolang-generation-jobs`).
const VIDEO_ASSET_KINDS = [
  'general',
  'character_action',
  'transition_video',
  'cover_video',
] as const;
type VideoAssetKind = (typeof VIDEO_ASSET_KINDS)[number];

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
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{
    mode?: string;
    prompt?: string;
    ref?: string;
    styleId?: string;
    draftId?: string;
    videoAssetKind?: string;
    targetCharacterId?: string;
    subjectNameHint?: string;
    referenceCharacterIds?: string;
    referenceSceneIds?: string;
    referencePropIds?: string;
    linkEpisodeId?: string;
    linkBreakpointKey?: string;
    continuityAssetId?: string;
    jobId?: string;
    skillId?: string;
  }>;
}) {
  const {
    mode,
    prompt,
    ref,
    styleId,
    draftId,
    videoAssetKind,
    targetCharacterId,
    subjectNameHint,
    referenceCharacterIds,
    referenceSceneIds,
    referencePropIds,
    linkEpisodeId,
    linkBreakpointKey,
    continuityAssetId,
    jobId,
    skillId,
  } = await searchParams;
  const t = await getTranslations('createPage');

  // A pre-AC-8 image link (an old bookmark or an unrendered notification):
  // an image draft reopens its card's workspace or its read-only job page.
  if (mode === 'image_creation') {
    const { locale } = await params;
    const draft = draftId
      ? await serverFetchOrNull<Draft>(`/v1/drafts/${encodeURIComponent(draftId)}`, {
          authenticated: true,
        })
      : null;
    redirect({ href: draft ? imageDraftHref(draft) : '/create', locale });
  }

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

  // `draftId` resumes a video creation session — its full version history
  // and latest output (see `GenerationVersionHistory`); audio still only
  // ever lands on `/jobs/[jobId]`. `image_to_video`/`video_to_video` sessions (remix,
  // "最近草稿" edit) never carry a `draftId` in the URL, so this only ever
  // resolves for a plain `text_to_video` mode session.
  const initialDraft =
    draftId && operation === 'text_to_video'
      ? ((await serverFetchOrNull<Draft>(`/v1/drafts/${draftId}`, { authenticated: true })) ??
        undefined)
      : undefined;

  // A notification click is `?draftId=&jobId=`; draft cards are
  // `?draftId=` only and resume `latest_job_id`. `jobId` is validated here
  // so the studio never has to distrust a raw query string.
  const resolvedJobId = parseJobId(jobId);

  // The character library's "生成动作视频" button deep-links here.
  const resolvedVideoAssetKind: VideoAssetKind | undefined = VIDEO_ASSET_KINDS.includes(
    videoAssetKind as VideoAssetKind,
  )
    ? (videoAssetKind as VideoAssetKind)
    : undefined;
  const resolvedReferenceCharacterIds = parseReferenceIds(referenceCharacterIds);
  const resolvedReferenceSceneIds = parseReferenceIds(referenceSceneIds);
  const resolvedReferencePropIds = parseReferenceIds(referencePropIds);
  // The previous script breakpoint's video, if any — see
  // `previousBoundVideoAssetId`/`buildBreakpointVideoHref`. Only meaningful
  // without an existing `draftId` (a resumed session already has its own
  // material); the studio itself re-derives that condition too.
  const resolvedContinuityAssetId = parseAssetId(continuityAssetId);
  const resolvedSkillId = parseSkillId(skillId);
  return (
    <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-6 px-4 py-6 sm:px-6">
      {resolvedMode === 'video_creation' ? (
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
          videoAssetKind: resolvedVideoAssetKind,
          targetCharacterId,
          subjectNameHint: subjectNameHint?.trim().slice(0, 60),
          linkBreakpointKey,
          continuitySourceAssetId: resolvedContinuityAssetId,
          skillId: resolvedSkillId,
        })}
        operation={operation}
        initialPrompt={prompt?.trim().slice(0, STUDIO_PROMPT_MAX_LENGTH)}
        reference={reference ?? undefined}
        initialDraft={initialDraft}
        initialJobId={resolvedJobId}
        style={style}
        initialVideoAssetKind={resolvedVideoAssetKind}
        initialTargetCharacterId={targetCharacterId}
        subjectNameHint={subjectNameHint?.trim().slice(0, 60) || undefined}
        initialReferenceCharacterIds={resolvedReferenceCharacterIds}
        initialReferenceSceneIds={resolvedReferenceSceneIds}
        initialReferencePropIds={resolvedReferencePropIds}
        linkEpisodeId={linkEpisodeId}
        linkBreakpointKey={linkBreakpointKey}
        continuitySourceAssetId={resolvedContinuityAssetId}
        initialSkillId={resolvedSkillId}
      />
    </div>
  );
}

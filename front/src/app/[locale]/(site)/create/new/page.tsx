import { getTranslations } from 'next-intl/server';

import { AudioGenerationStudio } from '@/components/studio/audio-generation-studio';
import { ImageGenerationStudio } from '@/components/studio/image-generation-studio';
import { VideoGenerationStudio } from '@/components/studio/video-generation-studio';
import { BackLink } from '@/components/ui/back-link';
import { PageHeading } from '@/components/ui/primitives';
import { serverFetchOrNull } from '@/lib/api/server';
import type { Draft, StyleGalleryEntry, WorkDetail } from '@/lib/api/types';

// `image_creation` is a URL-level mode only — the merged "图片创作" card from
// `create-mode-cards.tsx` — not a backend `Operation`. It always starts the
// studio on `text_to_image`; `ImageGenerationStudio` itself derives
// `image_to_image` the moment a reference image is attached (see
// `VideoGenerationStudio`'s own `text_to_video → image_to_video/video_to_video`
// derivation for the same pattern on the video side).
const MODES = ['image_creation', 'text_to_video', 'image_to_video', 'audio_generation'] as const;
type Mode = (typeof MODES)[number];

const OPERATION_BY_MODE: Record<
  Mode,
  'text_to_image' | 'text_to_video' | 'image_to_video' | 'audio_generation'
> = {
  image_creation: 'text_to_image',
  text_to_video: 'text_to_video',
  image_to_video: 'image_to_video',
  audio_generation: 'audio_generation',
};

const TITLE_KEYS: Record<Mode, string> = {
  image_creation: 'modeImageCreationTitle',
  text_to_video: 'modeTextToVideoTitle',
  image_to_video: 'modeImageToVideoTitle',
  audio_generation: 'modeAudioGenerationTitle',
};

const DESCRIPTION_KEYS: Record<Mode, string> = {
  image_creation: 'modeImageCreationDesc',
  text_to_video: 'modeTextToVideoDesc',
  image_to_video: 'modeImageToVideoDesc',
  audio_generation: 'modeAudioGenerationDesc',
};

const PROMPT_MAX_LENGTH = 600;

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
  }>;
}) {
  const { mode, prompt, ref, styleId, draftId } = await searchParams;
  const t = await getTranslations('createPage');

  const resolvedMode: Mode = MODES.includes(mode as Mode) ? (mode as Mode) : 'text_to_video';
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
  // `text_to_image`; video/audio still only ever land on `/jobs/[jobId]`.
  const initialDraft =
    draftId && operation === 'text_to_image'
      ? ((await serverFetchOrNull<Draft>(`/v1/drafts/${draftId}`, { authenticated: true })) ??
        undefined)
      : undefined;

  return (
    <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-6 px-4 py-6 sm:px-6">
      <BackLink href="/create">{t('backToCreate')}</BackLink>
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
        />
      ) : (
        <VideoGenerationStudio
          operation={operation}
          initialPrompt={prompt?.trim().slice(0, PROMPT_MAX_LENGTH)}
          reference={reference ?? undefined}
          initialStyleParams={style?.params}
          initialStyleGalleryId={style?.id}
        />
      )}
    </div>
  );
}

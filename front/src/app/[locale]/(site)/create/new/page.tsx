import { getTranslations } from 'next-intl/server';

import { GenerationStudio } from '@/components/studio/generation-studio';
import { PageHeading } from '@/components/ui/primitives';
import { serverFetchOrNull } from '@/lib/api/server';
import type { WorkDetail } from '@/lib/api/types';

const MODES = ['text_to_video', 'image_to_video', 'image_to_image', 'audio_generation'] as const;
type Mode = (typeof MODES)[number];

const TITLE_KEYS: Record<Mode, string> = {
  text_to_video: 'modeTextToVideoTitle',
  image_to_video: 'modeImageToVideoTitle',
  image_to_image: 'modeImageToImageTitle',
  audio_generation: 'modeAudioGenerationTitle',
};

const DESCRIPTION_KEYS: Record<Mode, string> = {
  text_to_video: 'modeTextToVideoDesc',
  image_to_video: 'modeImageToVideoDesc',
  image_to_image: 'modeImageToImageDesc',
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
  searchParams: Promise<{ mode?: string; prompt?: string; ref?: string }>;
}) {
  const { mode, prompt, ref } = await searchParams;
  const t = await getTranslations('createPage');

  const operation: Mode = MODES.includes(mode as Mode) ? (mode as Mode) : 'text_to_video';
  const title = t(TITLE_KEYS[operation]);
  const description = t(DESCRIPTION_KEYS[operation]);

  // `ref` is inspiration, not a remix source: it seeds the prompt and shows the
  // work the idea came from, but it never becomes `source_work_id`. Remixing
  // still has to go through `/remix/[workId]`, which checks the authorisation.
  const reference = ref ? await serverFetchOrNull<WorkDetail>(`/v1/works/${ref}`) : null;

  return (
    <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-6 px-4 py-6 sm:px-6">
      <PageHeading eyebrow={t('eyebrow')} title={title} description={description} />
      <GenerationStudio
        operation={operation}
        initialPrompt={prompt?.trim().slice(0, PROMPT_MAX_LENGTH)}
        reference={reference ?? undefined}
      />
    </div>
  );
}

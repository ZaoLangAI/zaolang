import { getTranslations } from 'next-intl/server';

import { GenerationStudio } from '@/components/studio/generation-studio';
import { PageHeading } from '@/components/ui/primitives';

const MODES = ['text_to_video', 'image_to_video'] as const;
type Mode = (typeof MODES)[number];

export async function generateMetadata() {
  const t = await getTranslations('createPage');
  return { title: t('startCreating') };
}

export default async function NewCreationPage({
  searchParams,
}: {
  searchParams: Promise<{ mode?: string }>;
}) {
  const { mode } = await searchParams;
  const t = await getTranslations('createPage');

  const operation: Mode = MODES.includes(mode as Mode) ? (mode as Mode) : 'text_to_video';
  const title =
    operation === 'image_to_video' ? t('modeImageToVideoTitle') : t('modeTextToVideoTitle');
  const description =
    operation === 'image_to_video' ? t('modeImageToVideoDesc') : t('modeTextToVideoDesc');

  return (
    <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-6 px-4 py-6 sm:px-6">
      <PageHeading eyebrow={t('eyebrow')} title={title} description={description} />
      <GenerationStudio operation={operation} />
    </div>
  );
}

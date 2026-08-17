'use client';

import { useTranslations } from 'next-intl';

import { useSession } from '@/components/auth/session-provider';
import {
  AudioGenerationIllustration,
  DramaIllustration,
  ImageCreationIllustration,
  ImageToVideoIllustration,
  RemixIllustration,
  ScriptIllustration,
  ShortformIllustration,
  TextToVideoIllustration,
} from '@/components/create/mode-illustrations';
import {
  IconArrowRight,
  IconImage,
  IconMessage,
  IconMic,
  IconPhone,
  IconRemix,
  IconSparkle,
  IconVideo,
} from '@/components/ui/icons';
import { useRouter } from '@/i18n/navigation';
import { cn } from '@/lib/cn';

type ModeId =
  | 'script'
  | 'image_creation'
  | 'text_to_video'
  | 'image_to_video'
  | 'audio_generation'
  | 'shortform'
  | 'drama'
  | 'remix';

const MODES: Array<{
  id: ModeId;
  icon: React.ReactNode;
  illustration: React.ReactNode;
  href: string;
  tone: string;
  accent: string;
}> = [
  {
    id: 'script',
    icon: <IconMessage className="size-5" />,
    illustration: <ScriptIllustration className="size-full" />,
    href: '/create/script',
    tone: 'bg-amber/15 text-amber',
    accent: 'text-amber',
  },
  {
    id: 'image_creation',
    icon: <IconSparkle className="size-5" />,
    illustration: <ImageCreationIllustration className="size-full" />,
    href: '/create/new?mode=image_creation',
    tone: 'bg-primary/15 text-primary',
    accent: 'text-primary',
  },
  {
    id: 'text_to_video',
    icon: <IconVideo className="size-5" />,
    illustration: <TextToVideoIllustration className="size-full" />,
    href: '/create/new?mode=text_to_video',
    tone: 'bg-primary/15 text-primary',
    accent: 'text-primary',
  },
  {
    id: 'image_to_video',
    icon: <IconImage className="size-5" />,
    illustration: <ImageToVideoIllustration className="size-full" />,
    href: '/create/new?mode=image_to_video',
    tone: 'bg-amber/15 text-amber',
    accent: 'text-amber',
  },
  {
    id: 'audio_generation',
    icon: <IconMic className="size-5" />,
    illustration: <AudioGenerationIllustration className="size-full" />,
    href: '/create/new?mode=audio_generation',
    tone: 'bg-primary/15 text-primary',
    accent: 'text-primary',
  },
  {
    id: 'shortform',
    icon: <IconPhone className="size-5" />,
    illustration: <ShortformIllustration className="size-full" />,
    href: '/create/short',
    tone: 'bg-amber/15 text-amber',
    accent: 'text-amber',
  },
  {
    id: 'drama',
    icon: <IconVideo className="size-5" />,
    illustration: <DramaIllustration className="size-full" />,
    href: '/create/drama',
    tone: 'bg-primary/15 text-primary',
    accent: 'text-primary',
  },
  {
    id: 'remix',
    icon: <IconRemix className="size-5" />,
    illustration: <RemixIllustration className="size-full" />,
    href: '/discover',
    tone: 'bg-primary/15 text-primary',
    accent: 'text-primary',
  },
];

/**
 * Entry points from the create page: stills, video, audio, shortform, remix.
 *
 * Choosing a mode is a protected action: it goes through `requireAuth` so an
 * anonymous visitor lands back on the same mode after signing in rather than
 * on the create page they already saw.
 */
export function CreateModeCards({ className }: { className?: string }) {
  const t = useTranslations('createPage');
  const router = useRouter();
  const { requireAuth } = useSession();

  const labels: Record<ModeId, { title: string; desc: string; tag: string }> = {
    script: {
      title: t('modeScriptTitle'),
      desc: t('modeScriptDesc'),
      tag: t('modeScriptTag'),
    },
    image_creation: {
      title: t('modeImageCreationTitle'),
      desc: t('modeImageCreationDesc'),
      tag: t('modeImageCreationTag'),
    },
    text_to_video: {
      title: t('modeTextToVideoTitle'),
      desc: t('modeTextToVideoDesc'),
      tag: t('modeTextToVideoTag'),
    },
    image_to_video: {
      title: t('modeImageToVideoTitle'),
      desc: t('modeImageToVideoDesc'),
      tag: t('modeImageToVideoTag'),
    },
    audio_generation: {
      title: t('modeAudioGenerationTitle'),
      desc: t('modeAudioGenerationDesc'),
      tag: t('modeAudioGenerationTag'),
    },
    shortform: {
      title: t('modeShortformTitle'),
      desc: t('modeShortformDesc'),
      tag: t('modeShortformTag'),
    },
    drama: {
      title: t('modeDramaTitle'),
      desc: t('modeDramaDesc'),
      tag: t('modeDramaTag'),
    },
    remix: { title: t('modeRemixTitle'), desc: t('modeRemixDesc'), tag: t('modeRemixTag') },
  };

  return (
    <ul className={cn('grid gap-4 sm:grid-cols-2 lg:grid-cols-4', className)}>
      {MODES.map((mode) => {
        const label = labels[mode.id];
        return (
          <li
            key={mode.id}
            className="flex flex-col overflow-hidden rounded-[var(--radius-md)] border border-border bg-surface transition-shadow hover:shadow-raised"
          >
            <div
              className={cn('relative aspect-[16/10] overflow-hidden bg-surface-soft', mode.accent)}
            >
              <div className="absolute inset-0 p-3 opacity-90">{mode.illustration}</div>
              <span
                className={cn(
                  'absolute bottom-3 left-3 grid size-9 place-items-center rounded-[10px]',
                  mode.tone,
                )}
              >
                {mode.icon}
              </span>
            </div>

            <div className="flex flex-1 flex-col p-4">
              <p
                className={cn(
                  'text-[11px]',
                  mode.id === 'text_to_video' || mode.id === 'image_creation'
                    ? 'text-muted'
                    : 'text-amber',
                )}
              >
                {label.tag}
              </p>
              <h3 className="mt-2 text-base font-semibold">{label.title}</h3>
              <p className="mt-1.5 flex-1 text-xs leading-relaxed text-muted">{label.desc}</p>

              <button
                type="button"
                onClick={() =>
                  requireAuth({ label: label.title, run: () => router.push(mode.href) })
                }
                className="mt-4 flex w-full items-center justify-center gap-2 rounded-[var(--radius-sm)] border border-border px-4 py-2.5 text-sm transition-colors hover:border-border-strong hover:bg-surface-soft"
              >
                {mode.id === 'remix' ? t('pickWork') : t('start')}
                <IconArrowRight className="size-4" />
              </button>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

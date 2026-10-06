'use client';

import { useTranslations } from 'next-intl';

import { useSession } from '@/components/auth/session-provider';
import {
  AudioGenerationIllustration,
  CharacterLibraryIllustration,
  MusicGenerationIllustration,
  PropIllustration,
  SceneLibraryIllustration,
  ScriptIllustration,
  TextToVideoIllustration,
} from '@/components/create/mode-illustrations';
import {
  IconArrowRight,
  IconBox,
  IconLandscape,
  IconMessage,
  IconMic,
  IconMusic,
  IconUser,
  IconVideo,
} from '@/components/ui/icons';
import { Button } from '@/components/ui/button';
import { useRouter } from '@/i18n/navigation';
import { cn } from '@/lib/cn';
import type { Me } from '@/lib/api/types';
import { prefetchStudio, type StudioPrefetchMode } from '@/lib/prefetch-studio';

type ModeId =
  | 'character_creation'
  | 'scene_creation'
  | 'prop_creation'
  | 'video_creation'
  | 'script'
  | 'audio_generation'
  | 'music_generation';

const MODES: Array<{
  id: ModeId;
  icon: React.ReactNode;
  illustration: React.ReactNode;
  href: string;
  tone: string;
  accent: string;
  /** The `/create/new` studio chunk to warm on hover; asset cards and the
   * script studio open their own routes. */
  studio?: StudioPrefetchMode;
  /** `undefined` means always on — the card libraries and `audio_generation`
   * have no gating flag at all on the backend (see `back/app/api/v1/jobs.py`'s
   * `VIDEO_OPERATIONS` check), so there is nothing in `me.features` to read. */
  flag?: keyof Me['features'];
}> = [
  // Image generation lives only in the card workspaces: each library is the
  // creation start, a card opens `/create/{kind}/[id]`.
  {
    id: 'character_creation',
    icon: <IconUser className="size-5" />,
    illustration: <CharacterLibraryIllustration className="size-full" />,
    href: '/create/characters',
    tone: 'bg-primary/15 text-primary',
    accent: 'text-primary',
  },
  {
    id: 'scene_creation',
    icon: <IconLandscape className="size-5" />,
    illustration: <SceneLibraryIllustration className="size-full" />,
    href: '/create/scenes',
    tone: 'bg-primary/15 text-primary',
    accent: 'text-primary',
  },
  {
    id: 'prop_creation',
    icon: <IconBox className="size-5" />,
    illustration: <PropIllustration className="size-full" />,
    href: '/create/props',
    tone: 'bg-primary/15 text-primary',
    accent: 'text-primary',
  },
  {
    id: 'video_creation',
    icon: <IconVideo className="size-5" />,
    illustration: <TextToVideoIllustration className="size-full" />,
    href: '/create/new?mode=video_creation',
    tone: 'bg-primary/15 text-primary',
    accent: 'text-primary',
    studio: 'video_creation',
    flag: 'video_generation',
  },
  {
    id: 'script',
    icon: <IconMessage className="size-5" />,
    illustration: <ScriptIllustration className="size-full" />,
    href: '/create/script',
    tone: 'bg-amber/15 text-amber',
    accent: 'text-amber',
    flag: 'script_studio',
  },
  {
    id: 'audio_generation',
    icon: <IconMic className="size-5" />,
    illustration: <AudioGenerationIllustration className="size-full" />,
    href: '/create/new?mode=audio_generation',
    tone: 'bg-primary/15 text-primary',
    accent: 'text-primary',
    studio: 'audio_generation',
  },
  {
    id: 'music_generation',
    icon: <IconMusic className="size-5" />,
    illustration: <MusicGenerationIllustration className="size-full" />,
    href: '/create/new?mode=music_generation',
    tone: 'bg-primary/15 text-primary',
    accent: 'text-primary',
    studio: 'music_generation',
  },
];

/** Cards whose tag is a plain category/price line rather than a highlight. */
const PRICED_TAG = new Set<ModeId>([
  'character_creation',
  'scene_creation',
  'prop_creation',
  'video_creation',
]);

/**
 * Entry points from the create page: the three asset libraries (角色 / 场景 /
 * 道具创作 — the only place images are generated), video, script, voice
 * audio, music/SFX.
 * Short-drama management has its own dedicated entry (`ShortformHeroBanner`
 * + the "最近短剧" section), not a card in this grid — see
 * `.cursor/skills/zaolang-editor-drama`.
 *
 * Choosing a mode is a protected action: it goes through `requireAuth` so an
 * anonymous visitor lands back on the same mode after signing in rather than
 * on the create page they already saw.
 */
export function CreateModeCards({ className }: { className?: string }) {
  const t = useTranslations('createPage');
  const router = useRouter();
  const { requireAuth, user } = useSession();

  const labels: Record<ModeId, { title: string; desc: string; tag: string }> = {
    script: {
      title: t('modeScriptTitle'),
      desc: t('modeScriptDesc'),
      tag: t('modeScriptTag'),
    },
    character_creation: {
      title: t('modeCharacterCreationTitle'),
      desc: t('modeCharacterCreationDesc'),
      tag: t('modeCharacterCreationTag'),
    },
    scene_creation: {
      title: t('modeSceneCreationTitle'),
      desc: t('modeSceneCreationDesc'),
      tag: t('modeSceneCreationTag'),
    },
    prop_creation: {
      title: t('modePropCreationTitle'),
      desc: t('modePropCreationDesc'),
      tag: t('modePropCreationTag'),
    },
    video_creation: {
      title: t('modeVideoCreationTitle'),
      desc: t('modeVideoCreationDesc'),
      tag: t('modeVideoCreationTag'),
    },
    audio_generation: {
      title: t('modeAudioGenerationTitle'),
      desc: t('modeAudioGenerationDesc'),
      tag: t('modeAudioGenerationTag'),
    },
    music_generation: {
      title: t('modeMusicGenerationTitle'),
      desc: t('modeMusicGenerationDesc'),
      tag: t('modeMusicGenerationTag'),
    },
  };

  return (
    <ul className={cn('grid gap-4 sm:grid-cols-2 lg:grid-cols-4', className)}>
      {MODES.map((mode) => {
        const label = labels[mode.id];
        // Fails open when the flag isn't known yet (session still loading,
        // or an anonymous visitor) — same stance `job-progress.tsx` takes on
        // `web_editor`, so a real toggle only ever narrows what an already
        // logged-in user can reach, never flickers a card off for everyone.
        const available = mode.flag ? (user?.features[mode.flag] ?? true) : true;
        return (
          <li
            key={mode.id}
            className={cn(
              'flex flex-col overflow-hidden rounded-[var(--radius-md)] border border-border bg-surface shadow-card transition-shadow',
              available ? 'hover:shadow-raised' : 'opacity-60',
            )}
            onMouseEnter={() => {
              if (available && mode.studio) prefetchStudio(mode.studio);
            }}
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
                className={cn('text-[11px]', PRICED_TAG.has(mode.id) ? 'text-muted' : 'text-amber')}
              >
                {available ? label.tag : t('modeUnavailable')}
              </p>
              <h3 className="mt-2 text-base font-semibold">{label.title}</h3>
              <p className="mt-1.5 flex-1 text-xs leading-relaxed text-muted">{label.desc}</p>

              <Button
                variant="secondary"
                fullWidth
                className="mt-4"
                disabled={!available}
                onFocus={() => {
                  if (available && mode.studio) prefetchStudio(mode.studio);
                }}
                onClick={() =>
                  requireAuth({ label: label.title, run: () => router.push(mode.href) })
                }
              >
                {t('start')}
                <IconArrowRight className="size-4" />
              </Button>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

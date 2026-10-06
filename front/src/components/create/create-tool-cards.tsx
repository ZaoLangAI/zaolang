'use client';

import { useTranslations } from 'next-intl';

import { useSession } from '@/components/auth/session-provider';
import {
  CanvasIllustration,
  VideoAnalysisIllustration,
} from '@/components/create/mode-illustrations';
import { IconArrowRight, IconBranch, IconSearch } from '@/components/ui/icons';
import { useRouter } from '@/i18n/navigation';
import type { Me } from '@/lib/api/types';
import { cn } from '@/lib/cn';

type ToolId = 'canvas' | 'video_analysis';

const TOOLS: Array<{
  id: ToolId;
  icon: React.ReactNode;
  illustration: React.ReactNode;
  href: string;
  tone: string;
  accent: string;
  /** `undefined` means always on. */
  flag?: keyof Me['features'];
}> = [
  {
    id: 'canvas',
    icon: <IconBranch className="size-5" />,
    illustration: <CanvasIllustration className="size-full" />,
    href: '/create/tools/canvas',
    tone: 'bg-primary/15 text-primary',
    accent: 'text-primary',
    flag: 'canvas_studio',
  },
  {
    id: 'video_analysis',
    icon: <IconSearch className="size-5" />,
    illustration: <VideoAnalysisIllustration className="size-full" />,
    href: '/create/tools/video-analysis',
    tone: 'bg-primary/15 text-primary',
    accent: 'text-primary',
    flag: 'video_analysis',
  },
];

/**
 * "创作工具" — a second, deliberately separate row below `CreateModeCards`
 * (see that file's own comment) for tools that assist an existing creation
 * rather than starting a brand-new one. First entry: "视频解析", which turns
 * a reference video into reusable camera/scene prompts instead of producing
 * a new asset — different enough in shape (structured text, not media) that
 * it earns its own section rather than a fifth card in that grid.
 *
 * Same protected-navigation gate as `CreateModeCards` (`requireAuth`) — an
 * anonymous visitor lands back on this tool after signing in. Whether the
 * tool itself is enabled reads `me.features` (same "fail open until known"
 * stance as `CreateModeCards`) so a disabled tool shows as such here
 * instead of only 404ing once the user is already inside the studio page.
 */
export function CreateToolCards({ className }: { className?: string }) {
  const t = useTranslations('createPage');
  const router = useRouter();
  const { requireAuth, user } = useSession();

  const labels: Record<ToolId, { title: string; desc: string; tag: string }> = {
    canvas: {
      title: t('toolCanvasTitle'),
      desc: t('toolCanvasDesc'),
      tag: t('toolCanvasTag'),
    },
    video_analysis: {
      title: t('toolVideoAnalysisTitle'),
      desc: t('toolVideoAnalysisDesc'),
      tag: t('toolVideoAnalysisTag'),
    },
  };

  return (
    <ul className={cn('grid gap-4 sm:grid-cols-2 lg:grid-cols-4', className)}>
      {TOOLS.map((tool) => {
        const label = labels[tool.id];
        const available = tool.flag ? (user?.features[tool.flag] ?? true) : true;
        return (
          <li
            key={tool.id}
            className={cn(
              'flex flex-col overflow-hidden rounded-[var(--radius-md)] border border-border bg-surface transition-shadow',
              available ? 'hover:shadow-raised' : 'opacity-60',
            )}
          >
            <div
              className={cn('relative aspect-[16/10] overflow-hidden bg-surface-soft', tool.accent)}
            >
              <div className="absolute inset-0 p-3 opacity-90">{tool.illustration}</div>
              <span
                className={cn(
                  'absolute bottom-3 left-3 grid size-9 place-items-center rounded-[10px]',
                  tool.tone,
                )}
              >
                {tool.icon}
              </span>
            </div>

            <div className="flex flex-1 flex-col p-4">
              <p className="text-[11px] text-muted">
                {available ? label.tag : t('modeUnavailable')}
              </p>
              <h3 className="mt-2 text-base font-semibold">{label.title}</h3>
              <p className="mt-1.5 flex-1 text-xs leading-relaxed text-muted">{label.desc}</p>

              <button
                type="button"
                disabled={!available}
                onClick={() =>
                  requireAuth({ label: label.title, run: () => router.push(tool.href) })
                }
                className="mt-4 flex w-full items-center justify-center gap-2 rounded-[var(--radius-sm)] border border-border px-4 py-2.5 text-sm transition-colors hover:border-border-strong hover:bg-surface-soft disabled:cursor-not-allowed disabled:opacity-70 disabled:hover:border-border disabled:hover:bg-transparent"
              >
                {t('start')}
                <IconArrowRight className="size-4" />
              </button>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

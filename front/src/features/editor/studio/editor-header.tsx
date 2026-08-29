'use client';

import { useTranslations } from 'next-intl';

import { ThemeMenu } from '@/components/layout/theme-menu';
import { IconButton } from '@/components/ui/button';
import { IconClose } from '@/components/ui/icons';
import { useRouter } from '@/i18n/navigation';

/**
 * Adapted from OpenCut's `components/editor/editor-header.tsx` — a slim
 * top bar carrying the project name and export/theme controls. Everything
 * OpenCut-specific (Discord link, feedback popover, rename/delete project
 * dialogs) is dropped; export lives in the pinned `ExportPanel` in the
 * properties column instead of a header button, since this route has no
 * `TopBar` at all — the theme toggle would otherwise be unreachable here.
 */
export function EditorHeader({ title, episodeId }: { title: string; episodeId: string | null }) {
  const t = useTranslations('editor');
  const router = useRouter();

  const closeStudio = () => {
    window.close();
    router.push(episodeId ? `/create/short/episodes/${episodeId}` : '/create/short');
  };

  return (
    <header className="flex h-[3.4rem] shrink-0 items-center justify-between border-b border-border px-3">
      <div className="flex min-w-0 items-center gap-2">
        <IconButton label={t('closeStudio')} onClick={closeStudio}>
          <IconClose className="size-4" />
        </IconButton>
        <span className="truncate text-sm font-semibold">{title}</span>
      </div>
      <ThemeMenu />
    </header>
  );
}

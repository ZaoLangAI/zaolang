'use client';

import { useTranslations } from 'next-intl';

import { ThemeMenu } from '@/components/layout/theme-menu';
import { IconButton } from '@/components/ui/button';
import { IconClose } from '@/components/ui/icons';

/**
 * Adapted from OpenCut's `components/editor/editor-header.tsx` — a slim
 * top bar carrying the project name and export/theme controls. Everything
 * OpenCut-specific (Discord link, feedback popover, rename/delete project
 * dialogs) is dropped; export lives in the pinned `ExportPanel` in the
 * properties column instead of a header button, since this route has no
 * `TopBar` at all — the theme toggle would otherwise be unreachable here.
 */
export function EditorHeader({ title }: { title: string }) {
  const t = useTranslations('editor');

  return (
    <header className="flex h-[3.4rem] shrink-0 items-center justify-between border-b border-border px-3">
      <div className="flex min-w-0 items-center gap-2">
        <IconButton label={t('closeStudio')} onClick={() => window.close()}>
          <IconClose className="size-4" />
        </IconButton>
        <span className="truncate text-sm font-semibold">{title}</span>
      </div>
      <ThemeMenu />
    </header>
  );
}

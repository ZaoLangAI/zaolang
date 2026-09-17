'use client';

import { useTranslations } from 'next-intl';

import { Button } from '@/components/ui/button';
import {
  IconDownload,
  IconImage,
  IconMonitor,
  IconPlus,
  IconRedo,
  IconSearch,
  IconSparkle,
  IconText,
  IconTrash,
  IconUndo,
  IconUpload,
} from '@/components/ui/icons';

import type { CanvasNodeKind } from './api';

/** The kinds a person can add by hand.
 *
 * Deliberately only the unbound ones: a `series` / `episode` / `shot` / `clip`
 * node stands for a real domain object, so it appears when that object exists
 * (seeded by `missingDomainNodes`) rather than being conjured on a canvas with
 * nothing behind it.
 */
export const ADDABLE_KINDS = [
  'note',
  'prompt',
  'image',
  'agent',
] as const satisfies readonly CanvasNodeKind[];

type AddableKind = (typeof ADDABLE_KINDS)[number];

const KIND_ICON: Record<AddableKind, React.ReactNode> = {
  note: <IconText className="size-3.5" />,
  prompt: <IconPlus className="size-3.5" />,
  image: <IconImage className="size-3.5" />,
  agent: <IconSparkle className="size-3.5" />,
};

export function CanvasToolbar({
  onAdd,
  onDeleteSelected,
  selectedCount,
  onUndo,
  onRedo,
  canUndo,
  canRedo,
  onExport,
  onImport,
  onOpenDirector,
  onToggleLibrary,
  libraryOpen,
}: {
  onAdd: (kind: CanvasNodeKind) => void;
  onDeleteSelected: () => void;
  selectedCount: number;
  onUndo: () => void;
  onRedo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  onExport: () => void;
  onImport: (file: File) => void;
  onOpenDirector: () => void;
  /** The prompt library drawer. Not an `ADDABLE_KINDS` entry: a blank `skill`
   * card binds nothing, so it would render as permanently stale — the library
   * is the only way a skill card gets a skill. */
  onToggleLibrary: () => void;
  libraryOpen: boolean;
}) {
  const t = useTranslations('canvas');
  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-[var(--radius-md)] border border-border bg-surface p-1.5 shadow-sm">
      {ADDABLE_KINDS.map((kind) => (
        <Button
          key={kind}
          size="sm"
          variant="ghost"
          icon={KIND_ICON[kind]}
          onClick={() => onAdd(kind)}
        >
          {t(`kind.${kind}`)}
        </Button>
      ))}
      <Button
        size="sm"
        variant="ghost"
        icon={<IconSearch className="size-3.5" />}
        aria-expanded={libraryOpen}
        onClick={onToggleLibrary}
      >
        {t('library.title')}
      </Button>
      <span className="mx-1 h-4 w-px bg-border" aria-hidden="true" />
      <Button
        size="sm"
        variant="ghost"
        icon={<IconTrash className="size-3.5" />}
        disabled={selectedCount === 0}
        onClick={onDeleteSelected}
      >
        {t('deleteSelected')}
      </Button>
      <span className="mx-1 h-4 w-px bg-border" aria-hidden="true" />
      <Button
        size="sm"
        variant="ghost"
        icon={<IconUndo className="size-3.5" />}
        disabled={!canUndo}
        onClick={onUndo}
      >
        {t('undo')}
      </Button>
      <Button
        size="sm"
        variant="ghost"
        icon={<IconRedo className="size-3.5" />}
        disabled={!canRedo}
        onClick={onRedo}
      >
        {t('redo')}
      </Button>
      <span className="mx-1 h-4 w-px bg-border" aria-hidden="true" />
      <Button
        size="sm"
        variant="ghost"
        icon={<IconMonitor className="size-3.5" />}
        onClick={onOpenDirector}
      >
        {t('director')}
      </Button>
      <span className="mx-1 h-4 w-px bg-border" aria-hidden="true" />
      <Button
        size="sm"
        variant="ghost"
        icon={<IconDownload className="size-3.5" />}
        onClick={onExport}
      >
        {t('exportCanvas')}
      </Button>
      <label className="inline-flex">
        <span className="sr-only">{t('importCanvas')}</span>
        <input
          type="file"
          accept="application/json,.json"
          className="sr-only"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) onImport(file);
            event.target.value = '';
          }}
        />
        <span className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-[var(--radius-sm)] px-3 text-sm text-text transition-colors hover:bg-surface-soft">
          <IconUpload className="size-3.5" />
          {t('importCanvas')}
        </span>
      </label>
    </div>
  );
}

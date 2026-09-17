'use client';

import { useTranslations } from 'next-intl';

import { Dialog } from '@/components/ui/dialog';

/** Every binding `useEditorShortcuts` (studio-shell.tsx) installs — keep the two in step. */
export const SHORTCUT_GROUPS: { group: string; items: { keys: string[]; label: string }[] }[] = [
  {
    group: 'shortcutGroupPlayback',
    items: [
      { keys: ['Space', 'K'], label: 'shortcutPlayPause' },
      { keys: ['J', 'L'], label: 'shortcutSeekSecond' },
      { keys: ['←', '→'], label: 'shortcutStepFrame' },
      { keys: ['Shift+←', 'Shift+→'], label: 'shortcutSeekFive' },
      { keys: ['Home', 'End'], label: 'shortcutHomeEnd' },
    ],
  },
  {
    group: 'shortcutGroupEditing',
    items: [
      { keys: ['S'], label: 'shortcutSplit' },
      { keys: ['W'], label: 'shortcutKeepLeft' },
      { keys: ['Q'], label: 'shortcutKeepRight' },
      { keys: ['Ctrl+D'], label: 'shortcutDuplicate' },
      { keys: ['Ctrl+C', 'Ctrl+V'], label: 'shortcutCopyPaste' },
      { keys: ['Delete', 'Backspace'], label: 'shortcutDelete' },
      { keys: ['Ctrl+Z', 'Ctrl+Shift+Z'], label: 'shortcutUndoRedo' },
      { keys: ['M'], label: 'shortcutMarker' },
      { keys: ['N'], label: 'shortcutSnapping' },
    ],
  },
  {
    group: 'shortcutGroupSelection',
    items: [
      { keys: ['Ctrl+A'], label: 'shortcutSelectAll' },
      { keys: ['Esc'], label: 'shortcutDeselect' },
      { keys: ['Shift+Click'], label: 'shortcutToggleSelect' },
      { keys: ['Drag'], label: 'shortcutMarquee' },
    ],
  },
  {
    group: 'shortcutGroupTimeline',
    items: [
      { keys: ['Ctrl+Wheel'], label: 'shortcutZoom' },
      { keys: ['Shift+Wheel'], label: 'shortcutScroll' },
      { keys: ['Shift+Drag'], label: 'shortcutDisableSnap' },
      { keys: ['?'], label: 'shortcutHelp' },
    ],
  },
];

export function ShortcutsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useTranslations('editor');
  return (
    <Dialog open={open} onClose={onClose} title={t('shortcutsTitle')} size="lg">
      <div className="grid gap-4 sm:grid-cols-2">
        {SHORTCUT_GROUPS.map((group) => (
          <section key={group.group} className="flex flex-col gap-1.5">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{t(group.group)}</h3>
            <ul className="flex flex-col divide-y divide-border rounded-[var(--radius-sm)] border border-border">
              {group.items.map((item) => (
                <li key={item.label} className="flex items-center justify-between gap-3 px-2 py-1.5 text-xs">
                  <span className="text-text">{t(item.label)}</span>
                  <span className="flex shrink-0 gap-1">
                    {item.keys.map((key) => (
                      <kbd
                        key={key}
                        className="rounded border border-border bg-surface-soft px-1.5 py-0.5 font-mono text-[10px] text-muted"
                      >
                        {key}
                      </kbd>
                    ))}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </Dialog>
  );
}

'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { IconButton } from '@/components/ui/button';
import { IconClose } from '@/components/ui/icons';

import { TICKS_PER_SECOND, type CanonicalDocument, type EditCommand, type TimelineElement } from './engine/ports';

interface CaptionDraft {
  text: string;
  start: string;
  duration: string;
}

function ticksToSecondsLabel(ticks: number): string {
  return (ticks / TICKS_PER_SECOND).toFixed(1);
}

function secondsLabelToTicks(value: string): number | null {
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds < 0) return null;
  return Math.round(seconds * TICKS_PER_SECOND);
}

function draftOf(element: TimelineElement): CaptionDraft {
  return {
    text: element.text ?? '',
    start: ticksToSecondsLabel(element.start_ticks),
    duration: ticksToSecondsLabel(element.duration_ticks),
  };
}

/**
 * Every subtitle on `trk_caption` in one scrollable list, editable inline —
 * the alternative was hunting for each caption block on the timeline (often
 * a few pixels wide once several are packed in) just to fix a typo or nudge
 * its timing. No new backend surface: text/timing edits go through the
 * existing `update_caption`, deletes through `delete_elements`, exactly the
 * same commands the timeline's own caption clips already use.
 */
export function CaptionBatchPanel({
  document,
  disabled,
  onApply,
}: {
  document: CanonicalDocument;
  disabled: boolean;
  onApply: (commands: EditCommand[]) => void;
}) {
  const t = useTranslations('editor');
  const captionTrack = document.tracks.find((track) => track.kind === 'caption');
  const captions = [...(captionTrack?.elements ?? [])].sort((a, b) => a.start_ticks - b.start_ticks);
  const [drafts, setDrafts] = useState<Record<string, CaptionDraft>>({});

  const setDraft = (element: TimelineElement, patch: Partial<CaptionDraft>) => {
    setDrafts((prev) => ({ ...prev, [element.id]: { ...(prev[element.id] ?? draftOf(element)), ...patch } }));
  };

  const commit = (element: TimelineElement) => {
    const draft = drafts[element.id];
    if (!draft) return;
    const startTicks = secondsLabelToTicks(draft.start);
    const durationTicks = secondsLabelToTicks(draft.duration);
    const update: Extract<EditCommand, { type: 'update_caption' }> = {
      type: 'update_caption',
      element_id: element.id,
    };
    let changed = false;
    if (draft.text !== (element.text ?? '')) {
      update.text = draft.text;
      changed = true;
    }
    if (startTicks !== null && startTicks !== element.start_ticks) {
      update.at_ticks = startTicks;
      changed = true;
    }
    if (durationTicks !== null && durationTicks > 0 && durationTicks !== element.duration_ticks) {
      update.duration_ticks = durationTicks;
      changed = true;
    }
    if (changed) onApply([update]);
    setDrafts((prev) => {
      const next = { ...prev };
      delete next[element.id];
      return next;
    });
  };

  if (captions.length === 0) {
    return <p className="text-xs text-muted">{t('captionBatchEmpty')}</p>;
  }

  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-muted">{t('captionBatchHint')}</p>
      <ul className="flex flex-col gap-2">
        {captions.map((element) => {
          const draft = drafts[element.id] ?? draftOf(element);
          return (
            <li
              key={element.id}
              className="flex flex-col gap-1.5 rounded-[var(--radius-sm)] border border-border p-2"
            >
              <textarea
                value={draft.text}
                disabled={disabled}
                rows={2}
                aria-label={t('captionBatchTextLabel')}
                onChange={(event) => setDraft(element, { text: event.target.value })}
                onBlur={() => commit(element)}
                className="w-full resize-none rounded-[var(--radius-sm)] border border-border bg-surface px-2 py-1 text-xs text-text"
              />
              <div className="flex flex-wrap items-center gap-2">
                <label className="flex items-center gap-1 text-[11px] text-muted">
                  {t('captionBatchStart')}
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    value={draft.start}
                    disabled={disabled}
                    onChange={(event) => setDraft(element, { start: event.target.value })}
                    onBlur={() => commit(element)}
                    className="w-16 rounded-[var(--radius-sm)] border border-border bg-surface px-1 py-0.5 text-[11px] text-text"
                  />
                  s
                </label>
                <label className="flex items-center gap-1 text-[11px] text-muted">
                  {t('captionBatchDuration')}
                  <input
                    type="number"
                    step="0.1"
                    min="0.1"
                    value={draft.duration}
                    disabled={disabled}
                    onChange={(event) => setDraft(element, { duration: event.target.value })}
                    onBlur={() => commit(element)}
                    className="w-16 rounded-[var(--radius-sm)] border border-border bg-surface px-1 py-0.5 text-[11px] text-text"
                  />
                  s
                </label>
                <IconButton
                  label={t('captionBatchDelete')}
                  variant="ghost"
                  size="sm"
                  className="ml-auto size-7"
                  disabled={disabled}
                  onClick={() => onApply([{ type: 'delete_elements', element_ids: [element.id] }])}
                >
                  <IconClose className="size-3.5" />
                </IconButton>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

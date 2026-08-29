'use client';

import { useTranslations } from 'next-intl';
import { useRef, useState } from 'react';

import { IconButton } from '@/components/ui/button';
import { IconClose, IconPlus, IconVolume, IconVolumeOff } from '@/components/ui/icons';
import { cn } from '@/lib/cn';

import {
  TICKS_PER_SECOND,
  type CanonicalDocument,
  type EditCommand,
  type TimelineElement,
  type TimelineTrack,
} from './engine/ports';
import { useEditorUi } from './store';

const MIN_DURATION_TICKS = Math.round(TICKS_PER_SECOND * 0.1);

function secondsLabel(ticks: number): string {
  return `${(ticks / TICKS_PER_SECOND).toFixed(2)}s`;
}

type DragMode = 'move' | 'trim-start' | 'trim-end';

interface DragState {
  elementId: string;
  mode: DragMode;
  pxPerTick: number;
  origin: TimelineElement;
  startClientX: number;
}

export function Timeline({
  document,
  durationTicks,
  disabled,
  playheadLabel,
  onSelect,
  onCommand,
}: {
  document: CanonicalDocument;
  durationTicks: number;
  disabled: boolean;
  playheadLabel: string;
  onSelect: (element: TimelineElement) => void;
  onCommand: (commands: EditCommand[]) => void;
}) {
  const t = useTranslations('editor');
  const kindLabel: Record<TimelineTrack['kind'], string> = {
    video: t('trackKindVideo'),
    audio: t('trackKindAudio'),
    caption: t('trackKindCaption'),
    overlay: t('trackKindOverlay'),
  };
  const selectedIds = useEditorUi((state) => state.selectedIds);
  const playheadTicks = useEditorUi((state) => state.playheadTicks);
  const setPlayhead = useEditorUi((state) => state.setPlayhead);
  const span = Math.max(durationTicks, TICKS_PER_SECOND);
  const dragRef = useRef<DragState | null>(null);
  const sortedTracks = [...document.tracks].sort(
    (a, b) => a.order - b.order || a.id.localeCompare(b.id),
  );
  const trackCountByKind = document.tracks.reduce<Record<string, number>>((acc, track) => {
    acc[track.kind] = (acc[track.kind] ?? 0) + 1;
    return acc;
  }, {});
  // Live-dragged position, shown instead of the document's value until the
  // pointer is released and the command is sent.
  const [preview, setPreview] = useState<{
    elementId: string;
    startTicks: number;
    durationTicks: number;
  } | null>(null);

  const beginDrag = (
    event: React.PointerEvent<HTMLElement>,
    element: TimelineElement,
    mode: DragMode,
  ) => {
    if (disabled) return;
    event.preventDefault();
    event.stopPropagation();
    const lane = event.currentTarget.closest<HTMLElement>('[data-lane]');
    const pxPerTick = (lane?.getBoundingClientRect().width ?? 1) / span;
    dragRef.current = {
      elementId: element.id,
      mode,
      pxPerTick: pxPerTick || 1,
      origin: element,
      startClientX: event.clientX,
    };
    onSelect(element);

    const onMove = (moveEvent: PointerEvent) => {
      const drag = dragRef.current;
      if (!drag) return;
      const deltaTicks = Math.round((moveEvent.clientX - drag.startClientX) / drag.pxPerTick);
      if (drag.mode === 'move') {
        const nextStart = Math.max(0, drag.origin.start_ticks + deltaTicks);
        setPreview({
          elementId: drag.elementId,
          startTicks: nextStart,
          durationTicks: drag.origin.duration_ticks,
        });
      } else if (drag.mode === 'trim-start') {
        const maxStart = drag.origin.start_ticks + drag.origin.duration_ticks - MIN_DURATION_TICKS;
        const nextStart = Math.min(maxStart, Math.max(0, drag.origin.start_ticks + deltaTicks));
        const nextDuration = drag.origin.start_ticks + drag.origin.duration_ticks - nextStart;
        setPreview({
          elementId: drag.elementId,
          startTicks: nextStart,
          durationTicks: nextDuration,
        });
      } else {
        const nextDuration = Math.max(MIN_DURATION_TICKS, drag.origin.duration_ticks + deltaTicks);
        setPreview({
          elementId: drag.elementId,
          startTicks: drag.origin.start_ticks,
          durationTicks: nextDuration,
        });
      }
    };

    const onUp = (upEvent: PointerEvent) => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      const drag = dragRef.current;
      dragRef.current = null;
      setPreview(null);
      if (!drag) return;
      const deltaTicks = Math.round((upEvent.clientX - drag.startClientX) / drag.pxPerTick);
      if (deltaTicks === 0) return;
      if (drag.mode === 'move') {
        const nextStart = Math.max(0, drag.origin.start_ticks + deltaTicks);
        onCommand([
          {
            type: 'move_elements',
            element_ids: [drag.elementId],
            delta_ticks: nextStart - drag.origin.start_ticks,
          },
        ]);
      } else if (drag.mode === 'trim-start') {
        const maxStart = drag.origin.start_ticks + drag.origin.duration_ticks - MIN_DURATION_TICKS;
        const nextStart = Math.min(maxStart, Math.max(0, drag.origin.start_ticks + deltaTicks));
        const shift = nextStart - drag.origin.start_ticks;
        onCommand([
          {
            type: 'trim_element',
            element_id: drag.elementId,
            start_ticks: nextStart,
            duration_ticks: drag.origin.start_ticks + drag.origin.duration_ticks - nextStart,
            source_in_ticks: Math.max(0, drag.origin.source_in_ticks + shift),
            source_out_ticks: drag.origin.source_out_ticks,
          },
        ]);
      } else {
        const nextDuration = Math.max(MIN_DURATION_TICKS, drag.origin.duration_ticks + deltaTicks);
        onCommand([
          {
            type: 'trim_element',
            element_id: drag.elementId,
            start_ticks: drag.origin.start_ticks,
            duration_ticks: nextDuration,
            source_in_ticks: drag.origin.source_in_ticks,
            source_out_ticks: drag.origin.source_in_ticks + nextDuration,
          },
        ]);
      }
    };

    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <input
        type="range"
        min={0}
        max={span}
        step={1}
        value={playheadTicks}
        aria-label={playheadLabel}
        disabled={disabled}
        onChange={(event) => setPlayhead(Number(event.target.value))}
        className="w-full shrink-0 accent-primary"
      />
      <ul className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto">
        {sortedTracks.map((track) => {
          const isAddable = track.kind === 'video' || track.kind === 'audio';
          const isOnlyOfKind = (trackCountByKind[track.kind] ?? 0) <= 1;
          return (
            <li
              key={track.id}
              className="flex items-center gap-2 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-2 py-1.5"
            >
              <div className="flex w-20 shrink-0 flex-col items-start gap-0.5">
                <p className="w-full truncate text-[11px] text-muted">
                  {track.label || kindLabel[track.kind]}
                </p>
                {isAddable ? (
                  <div className="flex items-center gap-0.5">
                    <IconButton
                      label={track.muted ? t('unmuteTrack') : t('muteTrack')}
                      variant="ghost"
                      size="sm"
                      className="size-7"
                      disabled={disabled}
                      onClick={() =>
                        onCommand([
                          { type: 'set_track_muted', track_id: track.id, muted: !track.muted },
                        ])
                      }
                    >
                      {track.muted ? (
                        <IconVolumeOff className="size-3.5" />
                      ) : (
                        <IconVolume className="size-3.5" />
                      )}
                    </IconButton>
                    <IconButton
                      label={t('removeTrack')}
                      variant="ghost"
                      size="sm"
                      className="size-7"
                      disabled={disabled || isOnlyOfKind || track.elements.length > 0}
                      onClick={() => onCommand([{ type: 'remove_track', track_id: track.id }])}
                    >
                      <IconClose className="size-3.5" />
                    </IconButton>
                  </div>
                ) : null}
              </div>
              <div data-lane className="relative h-10 min-w-0 flex-1 overflow-hidden rounded-sm bg-track">
                <span
                  className="absolute inset-y-0 w-px bg-primary"
                  style={{ left: `${(playheadTicks / span) * 100}%` }}
                />
                {track.elements.map((element) => {
                  const live = preview?.elementId === element.id ? preview : null;
                  const startTicks = live?.startTicks ?? element.start_ticks;
                  const elementDuration = live?.durationTicks ?? element.duration_ticks;
                  const isClip = element.type === 'clip';
                  return (
                    <button
                      key={element.id}
                      type="button"
                      disabled={disabled}
                      onClick={() => onSelect(element)}
                      onPointerDown={(event) => beginDrag(event, element, 'move')}
                      className={cn(
                        'group absolute top-1 h-8 rounded-sm border text-left text-[10px] text-on-primary',
                        isClip ? 'cursor-grab active:cursor-grabbing' : undefined,
                        selectedIds.includes(element.id)
                          ? 'border-primary bg-primary'
                          : 'border-transparent bg-primary/70 hover:bg-primary',
                      )}
                      style={{
                        left: `${(startTicks / span) * 100}%`,
                        width: `${Math.max(2, (elementDuration / span) * 100)}%`,
                      }}
                    >
                      <span className="block truncate px-2">
                        {element.text ?? element.asset_id ?? element.type} ·{' '}
                        {secondsLabel(elementDuration)}
                      </span>
                      {isClip ? (
                        <>
                          <span
                            role="presentation"
                            onPointerDown={(event) => beginDrag(event, element, 'trim-start')}
                            className="absolute inset-y-0 left-0 w-1.5 cursor-ew-resize bg-black/20 opacity-0 group-hover:opacity-100"
                          />
                          <span
                            role="presentation"
                            onPointerDown={(event) => beginDrag(event, element, 'trim-end')}
                            className="absolute inset-y-0 right-0 w-1.5 cursor-ew-resize bg-black/20 opacity-0 group-hover:opacity-100"
                          />
                        </>
                      ) : null}
                    </button>
                  );
                })}
              </div>
            </li>
          );
        })}
      </ul>
      <div className="flex shrink-0 flex-wrap gap-2">
        <IconButton
          label={t('addVideoTrack')}
          variant="secondary"
          size="sm"
          disabled={disabled}
          onClick={() => onCommand([{ type: 'add_track', kind: 'video' }])}
        >
          <IconPlus className="size-3.5" />
        </IconButton>
        <IconButton
          label={t('addAudioTrack')}
          variant="secondary"
          size="sm"
          disabled={disabled}
          onClick={() => onCommand([{ type: 'add_track', kind: 'audio' }])}
        >
          <IconPlus className="size-3.5" />
        </IconButton>
      </div>
    </div>
  );
}

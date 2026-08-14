'use client';

import { useRef, useState } from 'react';

import { cn } from '@/lib/cn';

import {
  TICKS_PER_SECOND,
  type CanonicalDocument,
  type EditCommand,
  type TimelineElement,
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
  const selectedIds = useEditorUi((state) => state.selectedIds);
  const playheadTicks = useEditorUi((state) => state.playheadTicks);
  const setPlayhead = useEditorUi((state) => state.setPlayhead);
  const span = Math.max(durationTicks, TICKS_PER_SECOND);
  const dragRef = useRef<DragState | null>(null);
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
        setPreview({ elementId: drag.elementId, startTicks: nextStart, durationTicks: nextDuration });
      } else {
        const nextDuration = Math.max(
          MIN_DURATION_TICKS,
          drag.origin.duration_ticks + deltaTicks,
        );
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
    <div className="flex flex-col gap-3">
      <input
        type="range"
        min={0}
        max={span}
        step={1}
        value={playheadTicks}
        aria-label={playheadLabel}
        disabled={disabled}
        onChange={(event) => setPlayhead(Number(event.target.value))}
        className="w-full accent-primary"
      />
      <ul className="flex flex-col gap-2">
        {document.tracks.map((track) => (
          <li
            key={track.id}
            className="rounded-[var(--radius-sm)] border border-border bg-surface-soft p-2"
          >
            <p className="mb-1 text-[11px] uppercase tracking-wide text-muted">{track.kind}</p>
            <div data-lane className="relative h-10 overflow-hidden rounded-sm bg-track">
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
        ))}
      </ul>
    </div>
  );
}

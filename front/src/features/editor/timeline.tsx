'use client';

import { useTranslations } from 'next-intl';
import { useRef, useState } from 'react';

import { Button, IconButton } from '@/components/ui/button';
import { IconBookmark, IconBookmarkFilled, IconClose, IconPlus, IconVolume, IconVolumeOff } from '@/components/ui/icons';
import { cn } from '@/lib/cn';

/** Not in the shared icon set (`@/components/ui/icons`) — kept local per the
 * "don't touch shared UI for editor-only visual needs" boundary. */
function IconMinus(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      aria-hidden="true"
      focusable="false"
      className="size-[1.15em]"
      {...props}
    >
      <path d="M5 12h14" />
    </svg>
  );
}

import {
  TICKS_PER_SECOND,
  type CanonicalDocument,
  type EditCommand,
  type ResolvedAsset,
  type TimelineElement,
  type TimelineTrack,
} from './engine/ports';
import { useEditorUi } from './store';
import { ClipThumbnails, ClipWaveform } from './timeline-media';

const MIN_DURATION_TICKS = Math.round(TICKS_PER_SECOND * 0.1);
const LABEL_WIDTH_PX = 84;
const BASE_PX_PER_SECOND = 48;
const ZOOM_MIN = 0.25;
const ZOOM_MAX = 8;
const ZOOM_STEP = 1.4;
const SNAP_PX_THRESHOLD = 8;

/** Reuses the script editor's categorical accent palette (`--color-script-*`
 * theme tokens) instead of inventing new CSS variables — see the "范围隔离"
 * constraint on not adding globally-scoped theme tokens for a single panel. */
const TRACK_ACCENT: Record<TimelineTrack['kind'], string> = {
  video: 'bg-script-scene',
  audio: 'bg-script-camera',
  caption: 'bg-script-dialogue',
  overlay: 'bg-script-action',
};

function secondsLabel(ticks: number): string {
  return `${(ticks / TICKS_PER_SECOND).toFixed(2)}s`;
}

/** `00:03.2` style timecode — minutes:seconds.decisecond. */
function formatTimecode(ticks: number): string {
  const totalDeciseconds = Math.round((Math.max(0, ticks) / TICKS_PER_SECOND) * 10);
  const minutes = Math.floor(totalDeciseconds / 600);
  const seconds = Math.floor((totalDeciseconds % 600) / 10);
  const deci = totalDeciseconds % 10;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}.${deci}`;
}

type DragMode = 'move' | 'trim-start' | 'trim-end';

interface DragState {
  elementId: string;
  trackId: string;
  mode: DragMode;
  pxPerTick: number;
  origin: TimelineElement;
  startClientX: number;
}

export function Timeline({
  document,
  assets,
  durationTicks,
  disabled,
  playheadLabel,
  onSelect,
  onCommand,
}: {
  document: CanonicalDocument;
  assets: ResolvedAsset[];
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
  const select = useEditorUi((state) => state.select);
  const playheadTicks = useEditorUi((state) => state.playheadTicks);
  const setPlayhead = useEditorUi((state) => state.setPlayhead);
  const span = Math.max(durationTicks, TICKS_PER_SECOND);
  const markers = [...document.markers].sort((a, b) => a.at_ticks - b.at_ticks);
  const [markerLabelDrafts, setMarkerLabelDrafts] = useState<Record<string, string>>({});
  const commitMarkerLabel = (markerId: string) => {
    const draft = markerLabelDrafts[markerId];
    if (draft === undefined) return;
    onCommand([{ type: 'update_marker', marker_id: markerId, label: draft || null }]);
    setMarkerLabelDrafts((prev) => {
      const next = { ...prev };
      delete next[markerId];
      return next;
    });
  };
  const [zoom, setZoom] = useState(1);
  const pxPerTick = (BASE_PX_PER_SECOND * zoom) / TICKS_PER_SECOND;
  const totalWidthPx = Math.max(240, span * pxPerTick);
  const dragRef = useRef<DragState | null>(null);
  const sortedTracks = [...document.tracks].sort(
    (a, b) => a.order - b.order || a.id.localeCompare(b.id),
  );
  const assetById = new Map(assets.map((asset) => [asset.asset_id, asset]));
  const trackCountByKind = document.tracks.reduce<Record<string, number>>((acc, track) => {
    acc[track.kind] = (acc[track.kind] ?? 0) + 1;
    return acc;
  }, {});
  // Live-dragged position, shown instead of the document's value until the
  // pointer is released and the command is sent. Mirrored into a ref because
  // `onUp` is a closure created once per drag (inside `beginDrag`) and needs
  // the *latest* value written by `onMove` — reading the `preview` state
  // variable there would see whatever it was when the drag started instead.
  type PreviewState = { elementId: string; startTicks: number; durationTicks: number } | null;
  const [preview, setPreviewState] = useState<PreviewState>(null);
  const previewRef = useRef<PreviewState>(null);
  const setPreview = (next: PreviewState) => {
    previewRef.current = next;
    setPreviewState(next);
  };

  const zoomBy = (factor: number) => {
    setZoom((current) => Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, current * factor)));
  };

  /** Shift/Ctrl/Cmd-click accumulates a multi-selection; a plain click
   * replaces it — the standard NLE/file-manager convention. `selectedIds`
   * was always an array (multi-select was only ever exposed for batch
   * "delete selected"), this just adds a way to actually build one via
   * pointer input instead of only programmatically. */
  const toggleSelect = (event: React.MouseEvent, element: TimelineElement) => {
    if (event.shiftKey || event.metaKey || event.ctrlKey) {
      const already = selectedIds.includes(element.id);
      select(already ? selectedIds.filter((id) => id !== element.id) : [...selectedIds, element.id]);
    } else {
      onSelect(element);
    }
  };

  const alignSelectedToPlayhead = () => {
    const elements = document.tracks.flatMap((track) => track.elements);
    const commands: EditCommand[] = [];
    for (const id of selectedIds) {
      const element = elements.find((candidate) => candidate.id === id);
      if (!element) continue;
      const delta = playheadTicks - element.start_ticks;
      if (delta !== 0) commands.push({ type: 'move_elements', element_ids: [id], delta_ticks: delta });
    }
    if (commands.length > 0) onCommand(commands);
  };

  const onWheelZoom = (event: React.WheelEvent<HTMLDivElement>) => {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    zoomBy(event.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP);
  };

  /** Snap targets: 0, the playhead, and every other element's two edges —
   * mirrors what most NLEs snap a dragged clip to. Threshold is expressed in
   * screen pixels so it stays a constant "feel" regardless of zoom level. */
  const snapTargets = (excludeElementId: string): number[] => {
    const targets = [0, playheadTicks];
    for (const track of document.tracks) {
      for (const element of track.elements) {
        if (element.id === excludeElementId) continue;
        targets.push(element.start_ticks, element.start_ticks + element.duration_ticks);
      }
    }
    return targets;
  };

  const snapTick = (candidate: number, targets: number[]): number => {
    const thresholdTicks = SNAP_PX_THRESHOLD / dragRef.current!.pxPerTick;
    let best = candidate;
    let bestDist = thresholdTicks;
    for (const target of targets) {
      const dist = Math.abs(candidate - target);
      if (dist <= bestDist) {
        bestDist = dist;
        best = target;
      }
    }
    return best;
  };

  const beginDrag = (
    event: React.PointerEvent<HTMLElement>,
    element: TimelineElement,
    trackId: string,
    mode: DragMode,
  ) => {
    if (disabled) return;
    event.preventDefault();
    event.stopPropagation();
    dragRef.current = {
      elementId: element.id,
      trackId,
      mode,
      pxPerTick,
      origin: element,
      startClientX: event.clientX,
    };
    // Skip here for a modified pointerdown so `toggleSelect`'s click handler
    // (which runs right after) is the one deciding add/remove-from-selection
    // — otherwise this would always collapse to a single selection first.
    if (!event.shiftKey && !event.metaKey && !event.ctrlKey) {
      onSelect(element);
    }

    const onMove = (moveEvent: PointerEvent) => {
      const drag = dragRef.current;
      if (!drag) return;
      const deltaTicks = Math.round((moveEvent.clientX - drag.startClientX) / drag.pxPerTick);
      const targets = snapTargets(drag.elementId);
      if (drag.mode === 'move') {
        const rawStart = drag.origin.start_ticks + deltaTicks;
        const rawEnd = rawStart + drag.origin.duration_ticks;
        const snappedStart = snapTick(rawStart, targets);
        const nextStart =
          snappedStart !== rawStart
            ? snappedStart
            : snapTick(rawEnd, targets) - drag.origin.duration_ticks;
        setPreview({
          elementId: drag.elementId,
          startTicks: Math.max(0, nextStart),
          durationTicks: drag.origin.duration_ticks,
        });
      } else if (drag.mode === 'trim-start') {
        const maxStart = drag.origin.start_ticks + drag.origin.duration_ticks - MIN_DURATION_TICKS;
        const rawStart = drag.origin.start_ticks + deltaTicks;
        const snappedStart = snapTick(rawStart, targets);
        const nextStart = Math.min(maxStart, Math.max(0, snappedStart));
        const nextDuration = drag.origin.start_ticks + drag.origin.duration_ticks - nextStart;
        setPreview({
          elementId: drag.elementId,
          startTicks: nextStart,
          durationTicks: nextDuration,
        });
      } else {
        const rawEnd = drag.origin.start_ticks + drag.origin.duration_ticks + deltaTicks;
        const snappedEnd = snapTick(rawEnd, targets);
        const nextDuration = Math.max(MIN_DURATION_TICKS, snappedEnd - drag.origin.start_ticks);
        setPreview({
          elementId: drag.elementId,
          startTicks: drag.origin.start_ticks,
          durationTicks: nextDuration,
        });
      }
    };

    const onUp = () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      const drag = dragRef.current;
      dragRef.current = null;
      const resolved = previewRef.current;
      setPreview(null);
      if (!drag || !resolved || resolved.elementId !== drag.elementId) return;
      if (drag.mode === 'move') {
        const delta = resolved.startTicks - drag.origin.start_ticks;
        if (delta === 0) return;
        onCommand([{ type: 'move_elements', element_ids: [drag.elementId], delta_ticks: delta }]);
      } else if (drag.mode === 'trim-start') {
        if (resolved.startTicks === drag.origin.start_ticks) return;
        const shift = resolved.startTicks - drag.origin.start_ticks;
        onCommand([
          {
            type: 'trim_element',
            element_id: drag.elementId,
            start_ticks: resolved.startTicks,
            duration_ticks: resolved.durationTicks,
            source_in_ticks: Math.max(0, drag.origin.source_in_ticks + shift),
            source_out_ticks: drag.origin.source_out_ticks,
          },
        ]);
      } else {
        if (resolved.durationTicks === drag.origin.duration_ticks) return;
        onCommand([
          {
            type: 'trim_element',
            element_id: drag.elementId,
            start_ticks: drag.origin.start_ticks,
            duration_ticks: resolved.durationTicks,
            source_in_ticks: drag.origin.source_in_ticks,
            source_out_ticks: drag.origin.source_in_ticks + resolved.durationTicks,
          },
        ]);
      }
    };

    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <div className="flex shrink-0 items-center justify-between gap-2">
        <p className="font-mono text-xs text-muted" aria-live="off">
          {formatTimecode(playheadTicks)} / {formatTimecode(span)}
        </p>
        <div className="flex items-center gap-1">
          <Button
            size="sm"
            variant="secondary"
            disabled={disabled || selectedIds.length === 0}
            onClick={alignSelectedToPlayhead}
            title={t('alignToPlayheadHint')}
          >
            {t('alignToPlayhead')}
          </Button>
          <IconButton
            label={t('markerAdd')}
            variant="ghost"
            size="sm"
            className="size-7"
            disabled={disabled}
            onClick={() => onCommand([{ type: 'add_marker', at_ticks: playheadTicks }])}
          >
            <IconBookmark className="size-3.5" />
          </IconButton>
          <IconButton
            label={t('timelineZoomOut')}
            variant="ghost"
            size="sm"
            className="size-7"
            disabled={zoom <= ZOOM_MIN}
            onClick={() => zoomBy(1 / ZOOM_STEP)}
          >
            <IconMinus className="size-3.5" />
          </IconButton>
          <span className="w-10 text-center text-[11px] text-muted">
            {Math.round(zoom * 100)}%
          </span>
          <IconButton
            label={t('timelineZoomIn')}
            variant="ghost"
            size="sm"
            className="size-7"
            disabled={zoom >= ZOOM_MAX}
            onClick={() => zoomBy(ZOOM_STEP)}
          >
            <IconPlus className="size-3.5" />
          </IconButton>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-auto" onWheel={onWheelZoom}>
        <div style={{ width: LABEL_WIDTH_PX + totalWidthPx }} className="flex flex-col gap-1">
          <div className="sticky top-0 z-20 flex items-center gap-2 bg-surface pb-1">
            <div className="sticky left-0 z-30 shrink-0 bg-surface" style={{ width: LABEL_WIDTH_PX }} />
            <div className="shrink-0" style={{ width: totalWidthPx }}>
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
            </div>
          </div>
          {markers.length > 0 ? (
            <div className="flex items-center gap-2 pb-1">
              <div className="sticky left-0 z-10 shrink-0 bg-surface" style={{ width: LABEL_WIDTH_PX }} />
              <div className="relative h-4 shrink-0" style={{ width: totalWidthPx }}>
                {markers.map((marker) => (
                  <button
                    key={marker.id}
                    type="button"
                    title={marker.label || secondsLabel(marker.at_ticks)}
                    aria-label={t('markerSeekTo', { time: secondsLabel(marker.at_ticks) })}
                    onClick={() => setPlayhead(marker.at_ticks)}
                    className="absolute top-0 -translate-x-1/2 text-primary hover:text-fg"
                    style={{ left: `${(marker.at_ticks / span) * 100}%` }}
                  >
                    <IconBookmarkFilled className="size-3.5" />
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          <ul className="flex flex-col gap-1">
            {sortedTracks.map((track) => {
              const isAddable = track.kind === 'video' || track.kind === 'audio';
              const isOnlyOfKind = (trackCountByKind[track.kind] ?? 0) <= 1;
              return (
                <li key={track.id} className="flex items-center gap-2">
                  <div
                    className="sticky left-0 z-10 flex shrink-0 flex-col items-start gap-0.5 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-2 py-1.5"
                    style={{ width: LABEL_WIDTH_PX }}
                  >
                    <span className="flex w-full items-center gap-1">
                      <span
                        aria-hidden
                        className={cn('size-1.5 shrink-0 rounded-full', TRACK_ACCENT[track.kind])}
                      />
                      <p className="min-w-0 flex-1 truncate text-[11px] text-muted">
                        {track.label || kindLabel[track.kind]}
                      </p>
                    </span>
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
                  <div
                    data-lane
                    className="relative h-10 shrink-0 overflow-hidden rounded-sm bg-track"
                    style={{ width: totalWidthPx }}
                  >
                    <span
                      aria-hidden
                      className={cn('absolute inset-y-0 left-0 w-0.5', TRACK_ACCENT[track.kind])}
                    />
                    <span
                      className="absolute inset-y-0 w-px bg-primary"
                      style={{ left: `${(playheadTicks / span) * 100}%` }}
                    />
                    {track.elements.map((element) => {
                      const live = preview?.elementId === element.id ? preview : null;
                      const startTicks = live?.startTicks ?? element.start_ticks;
                      const elementDuration = live?.durationTicks ?? element.duration_ticks;
                      const isClip = element.type === 'clip';
                      const elementWidthPx = Math.max(2, (elementDuration / span) * totalWidthPx);
                      const asset = element.asset_id ? assetById.get(element.asset_id) : undefined;
                      return (
                        <button
                          key={element.id}
                          type="button"
                          disabled={disabled}
                          onClick={(event) => toggleSelect(event, element)}
                          onPointerDown={(event) => beginDrag(event, element, track.id, 'move')}
                          className={cn(
                            'group absolute top-1 h-8 overflow-hidden rounded-sm border text-left text-[10px] text-on-primary',
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
                          {isClip && track.kind === 'video' && asset ? (
                            <ClipThumbnails
                              assetId={asset.asset_id}
                              url={asset.url}
                              sourceInTicks={element.source_in_ticks}
                              sourceOutTicks={element.source_out_ticks}
                              widthPx={elementWidthPx}
                            />
                          ) : null}
                          {isClip && track.kind === 'audio' && asset ? (
                            <ClipWaveform
                              assetId={asset.asset_id}
                              url={asset.url}
                              sourceInTicks={element.source_in_ticks}
                              sourceOutTicks={element.source_out_ticks}
                              widthPx={elementWidthPx}
                              heightPx={32}
                            />
                          ) : null}
                          <span className="relative block truncate px-2 drop-shadow-[0_1px_1px_rgba(0,0,0,0.6)]">
                            {element.text ?? element.asset_id ?? element.type} ·{' '}
                            {secondsLabel(elementDuration)}
                          </span>
                          {isClip ? (
                            <>
                              <span
                                role="presentation"
                                onPointerDown={(event) =>
                                  beginDrag(event, element, track.id, 'trim-start')
                                }
                                className="absolute inset-y-0 left-0 w-1.5 cursor-ew-resize bg-black/20 opacity-0 group-hover:opacity-100"
                              />
                              <span
                                role="presentation"
                                onPointerDown={(event) =>
                                  beginDrag(event, element, track.id, 'trim-end')
                                }
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
        </div>
      </div>
      {markers.length > 0 ? (
        <ul className="flex shrink-0 flex-wrap gap-1.5">
          {markers.map((marker) => (
            <li
              key={marker.id}
              className="flex items-center gap-1 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-1.5 py-0.5 text-[11px]"
            >
              <button
                type="button"
                onClick={() => setPlayhead(marker.at_ticks)}
                className="flex items-center gap-1 text-muted hover:text-fg"
                title={t('markerSeekTo', { time: secondsLabel(marker.at_ticks) })}
              >
                <IconBookmarkFilled className="size-3 text-primary" />
                {secondsLabel(marker.at_ticks)}
              </button>
              <input
                type="text"
                value={markerLabelDrafts[marker.id] ?? marker.label ?? ''}
                disabled={disabled}
                placeholder={t('markerLabelPlaceholder')}
                aria-label={t('markerLabelPlaceholder')}
                onChange={(event) =>
                  setMarkerLabelDrafts((prev) => ({ ...prev, [marker.id]: event.target.value }))
                }
                onBlur={() => commitMarkerLabel(marker.id)}
                className="w-24 rounded-[var(--radius-sm)] border border-border bg-surface px-1 py-0.5 text-fg"
              />
              <IconButton
                label={t('markerDelete')}
                variant="ghost"
                size="sm"
                className="size-6"
                disabled={disabled}
                onClick={() => onCommand([{ type: 'remove_marker', marker_id: marker.id }])}
              >
                <IconClose className="size-3" />
              </IconButton>
            </li>
          ))}
        </ul>
      ) : null}
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

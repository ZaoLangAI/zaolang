'use client';

import { useTranslations } from 'next-intl';
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent as ReactDragEvent,
  type PointerEvent as ReactPointerEvent,
} from 'react';

import {
  IconClose,
  IconEye,
  IconEyeOff,
  IconImage,
  IconMusic,
  IconSticker,
  IconText,
  IconVideo,
  IconVolume,
  IconVolumeOff,
} from '@/components/ui/icons';
import { cn } from '@/lib/cn';

import type { EditorActions } from '../actions';
import { newTrackId } from '../engine/canonical';
import {
  TICKS_PER_SECOND,
  type CanonicalDocument,
  type EditCommand,
  type Marker,
  type ResolvedAsset,
  type TimelineElement,
  type TimelineTrack,
} from '../engine/ports';
import { useEditorUi } from '../store';
import { ClipThumbnails, ClipWaveform } from '../timeline-media';
import {
  defaultInsertDuration,
  hasAssetDrag,
  hasFileDrag,
  readAssetDrag,
  trackKindForMedia,
} from './dnd';
import {
  DRAG_THRESHOLD_PX,
  MIN_ELEMENT_DURATION_TICKS,
  SNAP_PX_THRESHOLD,
  canvasFps,
  clampZoom,
  collectSnapTargets,
  edgeAutoScrollSpeed,
  formatSeconds,
  pxPerTick as pxPerTickAt,
  pxToTicks,
  rangesOverlap,
  snapTick,
  snapToFrame,
  ticksToPx,
  wheelZoomFactor,
  zoomToFit,
} from './geometry';
import { RULER_HEIGHT, Ruler } from './ruler';
import { TimelineToolbar } from './toolbar';

const HEADER_WIDTH = 112;
const LANE_HEIGHT = 52;
const ROW_GAP = 4;
const ROW_HEIGHT = LANE_HEIGHT + ROW_GAP;
const NEW_TRACK_ZONE_HEIGHT = 36;
const MAX_TRACKS_PER_KIND = 16;
/** Extra room past the last element so there is always somewhere to drop/extend. */
const TAIL_SECONDS = 10;

const TRACK_ACCENT: Record<TimelineTrack['kind'], string> = {
  video: 'bg-script-scene',
  audio: 'bg-script-camera',
  caption: 'bg-script-dialogue',
  overlay: 'bg-script-action',
};

type DragKind = 'pending' | 'move' | 'trim-start' | 'trim-end' | 'marquee' | 'scrub';

interface DragSession {
  kind: DragKind;
  /** What a still-pending press would become once it travels 5px. */
  intent: Exclude<DragKind, 'pending'>;
  pointerId: number;
  startClientX: number;
  startClientY: number;
  startContentX: number;
  startContentY: number;
  lastClientX: number;
  lastClientY: number;
  primaryId: string | null;
  elementIds: string[];
  origins: Map<string, TimelineElement>;
  /** All dragged elements share one track — the precondition for a vertical (cross-track) move. */
  singleTrackKind: TimelineTrack['kind'] | null;
  additive: boolean;
  initialSelection: string[];
  /** Filled in on the last move so pointer-up can commit without recomputing. */
  result: DragResult | null;
}

interface DragResult {
  deltaTicks: number;
  targetTrackId: string | null;
  newTrackKind: 'video' | 'audio' | null;
  trim: { startTicks: number; durationTicks: number; sourceInTicks: number } | null;
  snapTicks: number | null;
}

interface LivePosition {
  startTicks: number;
  durationTicks: number;
  sourceInTicks: number;
  trackId: string | typeof NEW_TRACK_LANE;
}

const NEW_TRACK_LANE = '__new_track__';

interface DropGhost {
  laneId: string | typeof NEW_TRACK_LANE | null;
  atTicks: number;
  durationTicks: number;
  kind: 'asset' | 'files';
}

function isModifier(event: { metaKey: boolean; ctrlKey: boolean }): boolean {
  return event.metaKey || event.ctrlKey;
}

/** Video on top (topmost layer first), then audio; caption above everything, overlay only if it has content. */
function displayTracks(document: CanonicalDocument): TimelineTrack[] {
  const byKind = (kind: TimelineTrack['kind']) => document.tracks.filter((track) => track.kind === kind);
  const video = byKind('video').sort((a, b) => b.order - a.order || a.id.localeCompare(b.id));
  const audio = byKind('audio').sort((a, b) => a.order - b.order || a.id.localeCompare(b.id));
  const caption = byKind('caption');
  const overlay = byKind('overlay').filter((track) => track.elements.length > 0);
  return [...caption, ...overlay, ...video, ...audio];
}

/**
 * The timeline: zoom-adaptive ruler with a draggable playhead, one lane per
 * track with thumbnails/waveforms, and the OpenCut interaction set — 5px
 * drag threshold, group moves, cross-track and new-track drops, trim
 * handles on clips and captions, marquee selection, edge auto-scroll,
 * media-library / external-file drop, and 10px edge snapping.
 */
export function Timeline({
  document,
  assets,
  durationTicks,
  disabled,
  actions,
  onCommand,
  onDropFiles,
}: {
  document: CanonicalDocument;
  assets: ResolvedAsset[];
  durationTicks: number;
  disabled: boolean;
  actions: EditorActions;
  onCommand: (commands: EditCommand[]) => void;
  onDropFiles: (files: File[], atTicks: number) => void;
}) {
  const t = useTranslations('editor');
  const kindLabel: Record<TimelineTrack['kind'], string> = {
    video: t('trackKindVideo'),
    audio: t('trackKindAudio'),
    caption: t('trackKindCaption'),
    overlay: t('trackKindOverlay'),
  };
  const mediaLabel: Record<string, string> = {
    video: t('mediaKindVideo'),
    audio: t('mediaKindAudio'),
    image: t('mediaKindImage'),
  };

  const selectedIds = useEditorUi((state) => state.selectedIds);
  const select = useEditorUi((state) => state.select);
  const playheadTicks = useEditorUi((state) => state.playheadTicks);
  const setPlayhead = useEditorUi((state) => state.setPlayhead);
  const playing = useEditorUi((state) => state.playing);
  const snappingEnabled = useEditorUi((state) => state.snappingEnabled);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [zoom, setZoom] = useState(1);
  const [viewport, setViewport] = useState({ scrollLeft: 0, width: 0 });
  const fittedRef = useRef(false);
  const pendingScrollLeftRef = useRef<number | null>(null);

  const fps = canvasFps(document.canvas);
  const pxPerTick = pxPerTickAt(zoom);
  const spanTicks = Math.max(durationTicks, TICKS_PER_SECOND) + TAIL_SECONDS * TICKS_PER_SECOND;
  const contentWidth = Math.max(viewport.width - HEADER_WIDTH, Math.ceil(ticksToPx(spanTicks, zoom)));
  const tracks = useMemo(() => displayTracks(document), [document]);
  const trackCountByKind = useMemo(() => {
    const counts: Partial<Record<TimelineTrack['kind'], number>> = {};
    for (const track of document.tracks) counts[track.kind] = (counts[track.kind] ?? 0) + 1;
    return counts;
  }, [document.tracks]);
  const assetById = useMemo(() => new Map(assets.map((asset) => [asset.asset_id, asset])), [assets]);
  const elementById = useMemo(() => {
    const map = new Map<string, { element: TimelineElement; track: TimelineTrack }>();
    for (const track of document.tracks) for (const element of track.elements) map.set(element.id, { element, track });
    return map;
  }, [document.tracks]);
  const markers = useMemo(() => [...document.markers].sort((a, b) => a.at_ticks - b.at_ticks), [document.markers]);
  const activeMarker = markers.find((marker) => marker.at_ticks === playheadTicks) ?? null;

  const dragRef = useRef<DragSession | null>(null);
  const autoScrollRafRef = useRef<number | null>(null);
  const [live, setLive] = useState<Map<string, LivePosition> | null>(null);
  const [snapLine, setSnapLine] = useState<number | null>(null);
  const [marquee, setMarquee] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
  const [dropGhost, setDropGhost] = useState<DropGhost | null>(null);
  const [newTrackLaneKind, setNewTrackLaneKind] = useState<'video' | 'audio' | null>(null);

  // --- viewport tracking -------------------------------------------------

  useEffect(() => {
    const node = scrollRef.current;
    if (!node) return;
    const measure = () => setViewport({ scrollLeft: node.scrollLeft, width: node.clientWidth });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  // Fit the whole cut into view once we know how wide the viewport is.
  useEffect(() => {
    if (fittedRef.current || viewport.width <= HEADER_WIDTH) return;
    fittedRef.current = true;
    setZoom(zoomToFit(Math.max(durationTicks, TICKS_PER_SECOND), viewport.width - HEADER_WIDTH));
  }, [viewport.width, durationTicks]);

  useLayoutEffect(() => {
    const node = scrollRef.current;
    if (!node || pendingScrollLeftRef.current == null) return;
    node.scrollLeft = Math.max(0, pendingScrollLeftRef.current);
    pendingScrollLeftRef.current = null;
    setViewport({ scrollLeft: node.scrollLeft, width: node.clientWidth });
  }, [zoom]);

  const zoomAround = useCallback(
    (nextZoomRaw: number, anchorClientX: number | null) => {
      const node = scrollRef.current;
      const nextZoom = clampZoom(nextZoomRaw);
      if (!node || nextZoom === zoom) return;
      const anchorPx =
        anchorClientX == null
          ? node.clientWidth / 2
          : Math.max(0, anchorClientX - node.getBoundingClientRect().left - HEADER_WIDTH);
      const anchorTicks = (node.scrollLeft + anchorPx) / pxPerTick;
      pendingScrollLeftRef.current = anchorTicks * pxPerTickAt(nextZoom) - anchorPx;
      setZoom(nextZoom);
    },
    [pxPerTick, zoom],
  );

  // React registers `onWheel` passively, so `preventDefault()` there cannot
  // stop the browser from also zooming/scrolling the page — a native
  // non-passive listener is the only way to own Ctrl+wheel.
  useEffect(() => {
    const node = scrollRef.current;
    if (!node) return;
    const onWheel = (event: WheelEvent) => {
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault();
        zoomAround(zoom * wheelZoomFactor(event.deltaY), event.clientX);
        return;
      }
      if (event.shiftKey && Math.abs(event.deltaX) < Math.abs(event.deltaY)) {
        event.preventDefault();
        node.scrollLeft += event.deltaY;
      }
    };
    node.addEventListener('wheel', onWheel, { passive: false });
    return () => node.removeEventListener('wheel', onWheel);
  }, [zoom, zoomAround]);

  // Keep the playhead in view while playing — jump so it sits at the centre.
  useEffect(() => {
    const node = scrollRef.current;
    if (!node || !playing) return;
    const playheadPx = ticksToPx(playheadTicks, zoom);
    const visibleWidth = node.clientWidth - HEADER_WIDTH;
    if (playheadPx < node.scrollLeft || playheadPx > node.scrollLeft + visibleWidth - 8) {
      node.scrollLeft = Math.max(0, playheadPx - visibleWidth / 2);
    }
  }, [playheadTicks, playing, zoom]);

  // --- coordinate helpers ------------------------------------------------

  const contentPoint = useCallback((clientX: number, clientY: number) => {
    const node = scrollRef.current!;
    const rect = node.getBoundingClientRect();
    return {
      x: clientX - rect.left - HEADER_WIDTH + node.scrollLeft,
      y: clientY - rect.top + node.scrollTop,
    };
  }, []);

  const rowIndexAtY = useCallback(
    (contentY: number): number | 'new' | null => {
      const y = contentY - RULER_HEIGHT;
      if (y < 0) return null;
      const index = Math.floor(y / ROW_HEIGHT);
      if (index >= tracks.length) {
        return y < tracks.length * ROW_HEIGHT + NEW_TRACK_ZONE_HEIGHT ? 'new' : null;
      }
      return index;
    },
    [tracks.length],
  );

  const snapThresholdTicks = SNAP_PX_THRESHOLD / pxPerTick;

  // Shift held during a gesture inverts the toolbar setting for that gesture only.
  const snapEnabledFor = useCallback(
    (event: { shiftKey: boolean }) => snappingEnabled !== event.shiftKey,
    [snappingEnabled],
  );

  // --- drag machinery ----------------------------------------------------

  const stopAutoScroll = () => {
    if (autoScrollRafRef.current != null) cancelAnimationFrame(autoScrollRafRef.current);
    autoScrollRafRef.current = null;
  };

  const computeMove = useCallback(
    (session: DragSession, clientX: number, clientY: number, shiftKey: boolean): DragResult => {
      const deltaPx = clientX - session.startClientX;
      let deltaTicks = Math.round(deltaPx / pxPerTick);
      const minStart = Math.min(...[...session.origins.values()].map((origin) => origin.start_ticks));
      deltaTicks = Math.max(deltaTicks, -minStart);
      let snapTicks: number | null = null;
      const primary = session.primaryId ? session.origins.get(session.primaryId) : undefined;
      if (primary && snapEnabledFor({ shiftKey })) {
        const targets = collectSnapTargets(document, { excludeIds: session.elementIds, playheadTicks });
        const startSnap = snapTick(primary.start_ticks + deltaTicks, targets, snapThresholdTicks);
        const endSnap = snapTick(primary.start_ticks + primary.duration_ticks + deltaTicks, targets, snapThresholdTicks);
        const startDistance = startSnap.snapped ? Math.abs(startSnap.ticks - (primary.start_ticks + deltaTicks)) : Infinity;
        const endDistance = endSnap.snapped
          ? Math.abs(endSnap.ticks - (primary.start_ticks + primary.duration_ticks + deltaTicks))
          : Infinity;
        if (startDistance <= endDistance && startSnap.snapped) {
          deltaTicks = Math.max(-minStart, startSnap.ticks - primary.start_ticks);
          snapTicks = startSnap.target;
        } else if (endSnap.snapped) {
          deltaTicks = Math.max(-minStart, endSnap.ticks - primary.start_ticks - primary.duration_ticks);
          snapTicks = endSnap.target;
        }
      }
      let targetTrackId: string | null = null;
      let newTrackKind: 'video' | 'audio' | null = null;
      if (session.singleTrackKind && primary) {
        const row = rowIndexAtY(contentPoint(clientX, clientY).y);
        if (typeof row === 'number') {
          const target = tracks[row];
          if (target && target.kind === session.singleTrackKind && target.id !== primary.track_id) {
            targetTrackId = target.id;
          }
        } else if (
          row === 'new' &&
          (session.singleTrackKind === 'video' || session.singleTrackKind === 'audio') &&
          (trackCountByKind[session.singleTrackKind] ?? 0) < MAX_TRACKS_PER_KIND
        ) {
          newTrackKind = session.singleTrackKind;
        }
      }
      return { deltaTicks, targetTrackId, newTrackKind, trim: null, snapTicks };
    },
    [contentPoint, document, playheadTicks, pxPerTick, rowIndexAtY, snapEnabledFor, snapThresholdTicks, trackCountByKind, tracks],
  );

  const computeTrim = useCallback(
    (session: DragSession, clientX: number, shiftKey: boolean): DragResult => {
      const origin = session.origins.get(session.primaryId!)!;
      const deltaTicks = Math.round((clientX - session.startClientX) / pxPerTick);
      const asset = origin.asset_id ? assetById.get(origin.asset_id) : undefined;
      const speed = Math.max(origin.speed_millipercent, 1) / 100_000;
      const sourceLength = asset?.duration_ticks ?? null;
      const targets = snapEnabledFor({ shiftKey })
        ? collectSnapTargets(document, { excludeIds: [origin.id], playheadTicks })
        : [];
      let snapTicks: number | null = null;
      if (session.intent === 'trim-end') {
        let end = origin.start_ticks + origin.duration_ticks + deltaTicks;
        const snapped = snapTick(end, targets, snapThresholdTicks);
        if (snapped.snapped) {
          end = snapped.ticks;
          snapTicks = snapped.target;
        }
        let duration = Math.max(MIN_ELEMENT_DURATION_TICKS, end - origin.start_ticks);
        if (sourceLength != null && origin.type !== 'caption') {
          const maxDuration = Math.max(MIN_ELEMENT_DURATION_TICKS, Math.floor((sourceLength - origin.source_in_ticks) / speed));
          duration = Math.min(duration, maxDuration);
        }
        return {
          deltaTicks: 0,
          targetTrackId: null,
          newTrackKind: null,
          snapTicks,
          trim: { startTicks: origin.start_ticks, durationTicks: duration, sourceInTicks: origin.source_in_ticks },
        };
      }
      let start = origin.start_ticks + deltaTicks;
      const snapped = snapTick(start, targets, snapThresholdTicks);
      if (snapped.snapped) {
        start = snapped.ticks;
        snapTicks = snapped.target;
      }
      const end = origin.start_ticks + origin.duration_ticks;
      // Can't reveal media before the source's own first frame.
      const earliest = origin.type === 'caption' ? 0 : Math.max(0, origin.start_ticks - Math.floor(origin.source_in_ticks / speed));
      start = Math.max(earliest, Math.min(start, end - MIN_ELEMENT_DURATION_TICKS));
      const shift = start - origin.start_ticks;
      return {
        deltaTicks: 0,
        targetTrackId: null,
        newTrackKind: null,
        snapTicks,
        trim: {
          startTicks: start,
          durationTicks: end - start,
          sourceInTicks: origin.type === 'caption' ? 0 : Math.max(0, origin.source_in_ticks + Math.round(shift * speed)),
        },
      };
    },
    [assetById, document, playheadTicks, pxPerTick, snapEnabledFor, snapThresholdTicks],
  );

  const scrubTo = useCallback(
    (clientX: number, shiftKey: boolean) => {
      const { x } = contentPoint(clientX, 0);
      let ticks = snapToFrame(Math.max(0, pxToTicks(x, zoom)), document.canvas);
      if (snapEnabledFor({ shiftKey })) {
        const snapped = snapTick(ticks, collectSnapTargets(document, { playheadTicks: null }), snapThresholdTicks);
        if (snapped.snapped) ticks = snapped.ticks;
      }
      setPlayhead(ticks);
    },
    [contentPoint, document, setPlayhead, snapEnabledFor, snapThresholdTicks, zoom],
  );

  const applyMarquee = useCallback(
    (session: DragSession, clientX: number, clientY: number) => {
      const point = contentPoint(clientX, clientY);
      const x0 = Math.min(session.startContentX, point.x);
      const x1 = Math.max(session.startContentX, point.x);
      const y0 = Math.min(session.startContentY, point.y);
      const y1 = Math.max(session.startContentY, point.y);
      setMarquee({ x0, y0, x1, y1 });
      const fromTicks = pxToTicks(x0, zoom);
      const toTicks = pxToTicks(x1, zoom);
      const hits: string[] = [];
      tracks.forEach((track, index) => {
        const rowTop = RULER_HEIGHT + index * ROW_HEIGHT;
        if (!rangesOverlap(rowTop, rowTop + LANE_HEIGHT, y0, y1)) return;
        for (const element of track.elements) {
          if (rangesOverlap(element.start_ticks, element.start_ticks + element.duration_ticks, fromTicks, toTicks)) {
            hits.push(element.id);
          }
        }
      });
      select(session.additive ? [...new Set([...session.initialSelection, ...hits])] : hits);
    },
    [contentPoint, select, tracks, zoom],
  );

  const updateDrag = useCallback(
    (clientX: number, clientY: number, shiftKey: boolean) => {
      const session = dragRef.current;
      if (!session) return;
      session.lastClientX = clientX;
      session.lastClientY = clientY;
      if (session.kind === 'pending') {
        const travelled = Math.hypot(clientX - session.startClientX, clientY - session.startClientY);
        if (travelled < DRAG_THRESHOLD_PX) return;
        session.kind = session.intent;
        if (session.kind === 'move' || session.kind === 'trim-start' || session.kind === 'trim-end') {
          // Dragging an unselected element selects it (and only it) first.
          if (session.primaryId && !session.initialSelection.includes(session.primaryId)) select([session.primaryId]);
        }
      }
      switch (session.kind) {
        case 'scrub':
          scrubTo(clientX, shiftKey);
          return;
        case 'marquee':
          applyMarquee(session, clientX, clientY);
          return;
        case 'move': {
          if (disabled) return;
          const result = computeMove(session, clientX, clientY, shiftKey);
          session.result = result;
          const next = new Map<string, LivePosition>();
          for (const origin of session.origins.values()) {
            next.set(origin.id, {
              startTicks: origin.start_ticks + result.deltaTicks,
              durationTicks: origin.duration_ticks,
              sourceInTicks: origin.source_in_ticks,
              trackId: result.newTrackKind ? NEW_TRACK_LANE : (result.targetTrackId ?? origin.track_id),
            });
          }
          setLive(next);
          setNewTrackLaneKind(result.newTrackKind);
          setSnapLine(result.snapTicks);
          return;
        }
        case 'trim-start':
        case 'trim-end': {
          if (disabled) return;
          const result = computeTrim(session, clientX, shiftKey);
          session.result = result;
          const origin = session.origins.get(session.primaryId!)!;
          setLive(
            new Map([
              [
                origin.id,
                {
                  startTicks: result.trim!.startTicks,
                  durationTicks: result.trim!.durationTicks,
                  sourceInTicks: result.trim!.sourceInTicks,
                  trackId: origin.track_id,
                },
              ],
            ]),
          );
          setSnapLine(result.snapTicks);
          return;
        }
        default:
          return;
      }
    },
    [applyMarquee, computeMove, computeTrim, disabled, scrubTo, select],
  );

  const finishDrag = useCallback(
    (event: PointerEvent) => {
      const session = dragRef.current;
      if (!session || session.pointerId !== event.pointerId) return;
      dragRef.current = null;
      stopAutoScroll();
      setLive(null);
      setSnapLine(null);
      setMarquee(null);
      setNewTrackLaneKind(null);

      if (session.kind === 'pending') {
        // A press that never travelled is a click.
        if (session.intent === 'marquee') {
          if (!session.additive) select([]);
        } else if (session.primaryId) {
          const id = session.primaryId;
          if (session.additive) {
            select(
              session.initialSelection.includes(id)
                ? session.initialSelection.filter((item) => item !== id)
                : [...session.initialSelection, id],
            );
          } else {
            select([id]);
          }
        }
        return;
      }
      if (disabled || !session.result) return;
      const { result } = session;
      if (session.kind === 'move') {
        if (result.deltaTicks === 0 && !result.targetTrackId && !result.newTrackKind) return;
        const commands: EditCommand[] = [];
        let trackId = result.targetTrackId ?? undefined;
        if (result.newTrackKind) {
          trackId = newTrackId();
          commands.push({ type: 'add_track', kind: result.newTrackKind, track_id: trackId });
        }
        commands.push({
          type: 'move_elements',
          element_ids: session.elementIds,
          delta_ticks: result.deltaTicks,
          ...(trackId ? { track_id: trackId } : {}),
        });
        onCommand(commands);
        return;
      }
      if ((session.kind === 'trim-start' || session.kind === 'trim-end') && result.trim) {
        const origin = session.origins.get(session.primaryId!)!;
        const { startTicks, durationTicks: nextDuration, sourceInTicks } = result.trim;
        if (startTicks === origin.start_ticks && nextDuration === origin.duration_ticks) return;
        if (origin.type === 'caption') {
          onCommand([
            { type: 'update_caption', element_id: origin.id, at_ticks: startTicks, duration_ticks: nextDuration },
          ]);
        } else {
          onCommand([
            {
              type: 'trim_element',
              element_id: origin.id,
              start_ticks: startTicks,
              duration_ticks: nextDuration,
              source_in_ticks: sourceInTicks,
              source_out_ticks: sourceInTicks + nextDuration,
            },
          ]);
        }
      }
    },
    [disabled, onCommand, select],
  );

  useEffect(() => {
    const onMove = (event: PointerEvent) => {
      const session = dragRef.current;
      if (!session || session.pointerId !== event.pointerId) return;
      updateDrag(event.clientX, event.clientY, event.shiftKey);
      // Edge auto-scroll: keep nudging while the pointer rests near an edge.
      stopAutoScroll();
      if (session.kind === 'pending' || session.kind === 'scrub') return;
      const node = scrollRef.current;
      if (!node) return;
      const tick = () => {
        const current = dragRef.current;
        const container = scrollRef.current;
        if (!current || !container) return;
        const rect = container.getBoundingClientRect();
        const speed = edgeAutoScrollSpeed(current.lastClientX, rect.left + HEADER_WIDTH, rect.right);
        if (speed !== 0) {
          const before = container.scrollLeft;
          container.scrollLeft = Math.max(0, before + speed);
          if (container.scrollLeft !== before) {
            // The content moved under a stationary pointer: re-derive from the same client point.
            current.startClientX -= container.scrollLeft - before;
            updateDrag(current.lastClientX, current.lastClientY, event.shiftKey);
          }
        }
        autoScrollRafRef.current = requestAnimationFrame(tick);
      };
      autoScrollRafRef.current = requestAnimationFrame(tick);
    };
    const onUp = (event: PointerEvent) => finishDrag(event);
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onUp);
    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointercancel', onUp);
      stopAutoScroll();
    };
  }, [finishDrag, updateDrag]);

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    const target = event.target as HTMLElement;
    if (target.closest('[data-track-header]') || target.closest('[data-marker-id]') || target.closest('input,button,textarea')) {
      return;
    }
    const point = contentPoint(event.clientX, event.clientY);
    const base = {
      pointerId: event.pointerId,
      startClientX: event.clientX,
      startClientY: event.clientY,
      startContentX: point.x,
      startContentY: point.y,
      lastClientX: event.clientX,
      lastClientY: event.clientY,
      additive: event.shiftKey || isModifier(event),
      initialSelection: selectedIds,
      result: null,
    };
    if (target.closest('[data-timeline-ruler]') || target.closest('[data-playhead-handle]')) {
      event.preventDefault();
      dragRef.current = {
        ...base,
        kind: 'scrub',
        intent: 'scrub',
        primaryId: null,
        elementIds: [],
        origins: new Map(),
        singleTrackKind: null,
      };
      scrubTo(event.clientX, event.shiftKey);
      return;
    }
    const elementNode = target.closest<HTMLElement>('[data-element-id]');
    if (elementNode) {
      event.preventDefault();
      const id = elementNode.dataset.elementId!;
      const found = elementById.get(id);
      if (!found) return;
      const trim = target.closest<HTMLElement>('[data-trim]')?.dataset.trim as 'start' | 'end' | undefined;
      const group = trim ? [id] : selectedIds.includes(id) ? selectedIds : [id];
      const origins = new Map<string, TimelineElement>();
      for (const memberId of group) {
        const member = elementById.get(memberId);
        if (member) origins.set(memberId, member.element);
      }
      const kinds = new Set([...origins.values()].map((origin) => elementById.get(origin.id)!.track.kind));
      const trackIds = new Set([...origins.values()].map((origin) => origin.track_id));
      dragRef.current = {
        ...base,
        kind: 'pending',
        intent: trim === 'start' ? 'trim-start' : trim === 'end' ? 'trim-end' : 'move',
        primaryId: id,
        elementIds: [...origins.keys()],
        origins,
        singleTrackKind: trackIds.size === 1 && kinds.size === 1 ? found.track.kind : null,
      };
      return;
    }
    if (target.closest('[data-lane]') || target.closest('[data-new-track-zone]') || target === scrollRef.current) {
      dragRef.current = {
        ...base,
        kind: 'pending',
        intent: 'marquee',
        primaryId: null,
        elementIds: [],
        origins: new Map(),
        singleTrackKind: null,
      };
    }
  };

  // --- media library / file drop ----------------------------------------

  const ghostFor = (event: ReactDragEvent<HTMLDivElement>): DropGhost | null => {
    const asset = hasAssetDrag(event.dataTransfer);
    const files = hasFileDrag(event.dataTransfer);
    if (!asset && !files) return null;
    const point = contentPoint(event.clientX, event.clientY);
    let atTicks = Math.max(0, pxToTicks(point.x, zoom));
    if (snapEnabledFor(event)) {
      const snapped = snapTick(atTicks, collectSnapTargets(document, { playheadTicks }), snapThresholdTicks);
      if (snapped.snapped) atTicks = snapped.ticks;
    }
    if (files) return { laneId: null, atTicks, durationTicks: 3 * TICKS_PER_SECOND, kind: 'files' };
    const row = rowIndexAtY(point.y);
    const track = typeof row === 'number' ? tracks[row] : undefined;
    return {
      laneId: track && (track.kind === 'video' || track.kind === 'audio') ? track.id : row === 'new' ? NEW_TRACK_LANE : null,
      atTicks,
      durationTicks: 3 * TICKS_PER_SECOND,
      kind: 'asset',
    };
  };

  const onDragOver = (event: ReactDragEvent<HTMLDivElement>) => {
    if (disabled) return;
    const ghost = ghostFor(event);
    if (!ghost) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
    setDropGhost(ghost);
  };

  const onDrop = (event: ReactDragEvent<HTMLDivElement>) => {
    setDropGhost(null);
    if (disabled) return;
    const ghost = ghostFor(event);
    if (!ghost) return;
    event.preventDefault();
    if (ghost.kind === 'files') {
      const files = Array.from(event.dataTransfer.files);
      if (files.length) onDropFiles(files, ghost.atTicks);
      return;
    }
    const payload = readAssetDrag(event.dataTransfer);
    if (!payload) return;
    const kind = trackKindForMedia(payload.media_type);
    const duration = defaultInsertDuration(payload);
    const commands: EditCommand[] = [];
    let trackId: string | null = null;
    const hovered = ghost.laneId && ghost.laneId !== NEW_TRACK_LANE ? document.tracks.find((track) => track.id === ghost.laneId) : null;
    if (hovered && hovered.kind === kind) {
      trackId = hovered.id;
    } else if ((trackCountByKind[kind] ?? 0) < MAX_TRACKS_PER_KIND && (ghost.laneId === NEW_TRACK_LANE || hovered)) {
      trackId = newTrackId();
      commands.push({ type: 'add_track', kind, track_id: trackId });
    } else {
      // Dropped on the ruler/gap: the first track of the right kind.
      trackId = document.tracks.find((track) => track.kind === kind)?.id ?? null;
    }
    if (!trackId) return;
    commands.push({
      type: 'insert_clip',
      track_id: trackId,
      asset_id: payload.asset_id,
      at_ticks: ghost.atTicks,
      duration_ticks: duration,
    });
    onCommand(commands);
  };

  // --- render ------------------------------------------------------------

  const visibleFromTicks = Math.max(0, pxToTicks(viewport.scrollLeft - 100, zoom));
  const visibleToTicks = pxToTicks(viewport.scrollLeft + Math.max(viewport.width, 1) + 100, zoom);

  const laneContents = useMemo(() => {
    const map = new Map<string, { element: TimelineElement; position: LivePosition; sourceTrack: TimelineTrack }[]>();
    for (const track of document.tracks) {
      for (const element of track.elements) {
        const position = live?.get(element.id) ?? {
          startTicks: element.start_ticks,
          durationTicks: element.duration_ticks,
          sourceInTicks: element.source_in_ticks,
          trackId: element.track_id,
        };
        const list = map.get(position.trackId) ?? [];
        list.push({ element, position, sourceTrack: track });
        map.set(position.trackId, list);
      }
    }
    return map;
  }, [document.tracks, live]);

  const onMarkerClick = (marker: Marker) => setPlayhead(marker.at_ticks);
  const onMarkerLabelChange = (marker: Marker, label: string) =>
    onCommand([{ type: 'update_marker', marker_id: marker.id, label: label || null }]);

  const playheadPx = ticksToPx(playheadTicks, zoom);
  const totalRowsHeight = tracks.length * ROW_HEIGHT + NEW_TRACK_ZONE_HEIGHT;

  const renderElement = (
    entry: { element: TimelineElement; position: LivePosition; sourceTrack: TimelineTrack },
    laneKind: TimelineTrack['kind'],
  ) => {
    const { element, position } = entry;
    const widthPx = Math.max(4, ticksToPx(position.durationTicks, zoom));
    const leftPx = ticksToPx(position.startTicks, zoom);
    const asset = element.asset_id ? assetById.get(element.asset_id) : undefined;
    const isCaption = element.type === 'caption';
    const isSelected = selectedIds.includes(element.id);
    const isLive = live?.has(element.id) ?? false;
    const mediaKind = asset?.media_type ?? (asset?.mime_type.startsWith('audio/') ? 'audio' : asset?.mime_type.startsWith('image/') ? 'image' : 'video');
    const label = isCaption
      ? element.text ?? ''
      : `${element.type === 'sticker' ? t('elementSticker') : mediaLabel[mediaKind] ?? mediaLabel.video} · ${element.asset_id?.slice(-4) ?? ''}`;
    return (
      <div
        key={element.id}
        data-element-id={element.id}
        role="option"
        aria-selected={isSelected}
        aria-label={`${label} ${formatSeconds(position.durationTicks)}`}
        className={cn(
          'group absolute top-1 h-[44px] select-none overflow-hidden rounded-sm border text-left text-[10px] text-on-primary',
          isCaption ? 'bg-script-dialogue/80' : element.type === 'sticker' ? 'bg-accent/80' : 'bg-primary/70',
          disabled ? 'cursor-default' : 'cursor-grab active:cursor-grabbing',
          isSelected ? 'border-white ring-2 ring-primary' : 'border-transparent hover:brightness-110',
          isLive && 'opacity-90 shadow-lg',
        )}
        style={{ left: leftPx, width: widthPx }}
      >
        {!isCaption && laneKind === 'video' && asset && mediaKind === 'image' ? (
          // eslint-disable-next-line @next/next/no-img-element -- signed, short-lived URL; not a static asset
          <img src={asset.url} alt="" aria-hidden className="pointer-events-none absolute inset-0 h-full w-full object-cover opacity-60" />
        ) : null}
        {!isCaption && laneKind === 'video' && asset && mediaKind === 'video' ? (
          <ClipThumbnails
            assetId={asset.asset_id}
            url={asset.url}
            sourceInTicks={position.sourceInTicks}
            sourceOutTicks={position.sourceInTicks + position.durationTicks}
            widthPx={widthPx}
          />
        ) : null}
        {!isCaption && (laneKind === 'audio' || mediaKind === 'audio') && asset ? (
          <ClipWaveform
            assetId={asset.asset_id}
            url={asset.url}
            sourceInTicks={position.sourceInTicks}
            sourceOutTicks={position.sourceInTicks + position.durationTicks}
            widthPx={widthPx}
            heightPx={44}
          />
        ) : null}
        <span className="pointer-events-none relative flex items-center gap-1 truncate px-1.5 pt-0.5 drop-shadow-[0_1px_1px_rgba(0,0,0,0.6)]">
          {isCaption ? <IconText className="size-3 shrink-0" /> : element.type === 'sticker' ? <IconSticker className="size-3 shrink-0" /> : null}
          <span className="truncate">{label}</span>
          <span className="ml-auto shrink-0 tabular-nums opacity-80">{formatSeconds(position.durationTicks)}</span>
        </span>
        {(element.transition_in || element.transition_out) && (
          <span className="pointer-events-none absolute inset-x-0 bottom-0 flex justify-between px-0.5 text-[8px] opacity-80">
            <span>{element.transition_in ? '◢' : ''}</span>
            <span>{element.transition_out ? '◣' : ''}</span>
          </span>
        )}
        {!disabled ? (
          <>
            <span
              data-trim="start"
              role="presentation"
              className="absolute inset-y-0 left-0 w-2 cursor-ew-resize bg-white/0 group-hover:bg-white/30"
            />
            <span
              data-trim="end"
              role="presentation"
              className="absolute inset-y-0 right-0 w-2 cursor-ew-resize bg-white/0 group-hover:bg-white/30"
            />
          </>
        ) : null}
      </div>
    );
  };

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface">
      <TimelineToolbar
        actions={actions}
        disabled={disabled}
        hasSelection={selectedIds.length > 0}
        snappingEnabled={snappingEnabled}
        zoom={zoom}
        onZoomChange={(next) => zoomAround(next, null)}
        playheadTicks={playheadTicks}
        durationTicks={durationTicks}
        fps={fps}
        activeMarker={activeMarker}
        onMarkerLabelChange={onMarkerLabelChange}
      />
      <div
        ref={scrollRef}
        className="relative min-h-0 flex-1 overflow-auto"
        onScroll={(event) => {
          const node = event.currentTarget;
          setViewport({ scrollLeft: node.scrollLeft, width: node.clientWidth });
        }}
        onPointerDown={onPointerDown}
        onDragOver={onDragOver}
        onDragLeave={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDropGhost(null);
        }}
        onDrop={onDrop}
      >
        <div className="relative" style={{ width: HEADER_WIDTH + contentWidth, minHeight: RULER_HEIGHT + totalRowsHeight }}>
          {/* Ruler row (sticky at the top) */}
          <div className="sticky top-0 z-30 flex" style={{ height: RULER_HEIGHT }}>
            <div
              data-track-header
              className="sticky left-0 z-40 shrink-0 border-b border-r border-border bg-surface"
              style={{ width: HEADER_WIDTH, height: RULER_HEIGHT }}
            />
            <Ruler
              zoom={zoom}
              fps={fps}
              widthPx={contentWidth}
              visibleFromTicks={visibleFromTicks}
              visibleToTicks={visibleToTicks}
              markers={markers}
              playheadTicks={playheadTicks}
              activeMarkerId={activeMarker?.id ?? null}
              onMarkerClick={onMarkerClick}
            />
          </div>

          {/* Track rows */}
          {tracks.map((track, index) => {
            const isAddable = track.kind === 'video' || track.kind === 'audio';
            const isOnlyOfKind = (trackCountByKind[track.kind] ?? 0) <= 1;
            const contents = laneContents.get(track.id) ?? [];
            return (
              <div key={track.id} className="flex" style={{ height: ROW_HEIGHT, paddingBottom: ROW_GAP }}>
                <div
                  data-track-header
                  className="sticky left-0 z-20 flex shrink-0 items-center gap-1 border-r border-border bg-surface-soft px-2"
                  style={{ width: HEADER_WIDTH, height: LANE_HEIGHT }}
                >
                  <span aria-hidden className={cn('h-6 w-1 shrink-0 rounded-full', TRACK_ACCENT[track.kind])} />
                  <span className="shrink-0 text-muted">
                    {track.kind === 'video' ? (
                      <IconVideo className="size-3.5" />
                    ) : track.kind === 'audio' ? (
                      <IconMusic className="size-3.5" />
                    ) : track.kind === 'caption' ? (
                      <IconText className="size-3.5" />
                    ) : (
                      <IconImage className="size-3.5" />
                    )}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-[11px] text-muted" title={track.label || kindLabel[track.kind]}>
                    {track.label || `${kindLabel[track.kind]}${isAddable && !isOnlyOfKind ? ` ${index + 1}` : ''}`}
                  </span>
                  {isAddable ? (
                    <span className="flex shrink-0 items-center">
                      <button
                        type="button"
                        title={track.kind === 'video' ? (track.muted ? t('showTrack') : t('hideTrack')) : track.muted ? t('unmuteTrack') : t('muteTrack')}
                        aria-label={track.kind === 'video' ? (track.muted ? t('showTrack') : t('hideTrack')) : track.muted ? t('unmuteTrack') : t('muteTrack')}
                        aria-pressed={track.muted}
                        disabled={disabled}
                        onClick={() => onCommand([{ type: 'set_track_muted', track_id: track.id, muted: !track.muted }])}
                        className={cn(
                          'inline-flex size-6 items-center justify-center rounded-[var(--radius-sm)] hover:bg-surface disabled:opacity-40',
                          track.muted ? 'text-danger' : 'text-muted',
                        )}
                      >
                        {track.kind === 'video' ? (
                          track.muted ? <IconEyeOff className="size-3.5" /> : <IconEye className="size-3.5" />
                        ) : track.muted ? (
                          <IconVolumeOff className="size-3.5" />
                        ) : (
                          <IconVolume className="size-3.5" />
                        )}
                      </button>
                      {!isOnlyOfKind && track.elements.length === 0 ? (
                        <button
                          type="button"
                          title={t('removeTrack')}
                          aria-label={t('removeTrack')}
                          disabled={disabled}
                          onClick={() => onCommand([{ type: 'remove_track', track_id: track.id }])}
                          className="inline-flex size-6 items-center justify-center rounded-[var(--radius-sm)] text-muted hover:bg-surface hover:text-danger disabled:opacity-40"
                        >
                          <IconClose className="size-3" />
                        </button>
                      ) : null}
                    </span>
                  ) : null}
                </div>
                <div
                  data-lane
                  data-lane-track-id={track.id}
                  className={cn('relative shrink-0 bg-track', track.muted && 'opacity-60')}
                  style={{ width: contentWidth, height: LANE_HEIGHT }}
                >
                  {contents.map((entry) => renderElement(entry, track.kind))}
                  {dropGhost && dropGhost.laneId === track.id ? (
                    <div
                      aria-hidden
                      className="pointer-events-none absolute top-1 h-[44px] rounded-sm border-2 border-dashed border-primary bg-primary/20"
                      style={{ left: ticksToPx(dropGhost.atTicks, zoom), width: Math.max(4, ticksToPx(dropGhost.durationTicks, zoom)) }}
                    />
                  ) : null}
                </div>
              </div>
            );
          })}

          {/* New-track drop zone */}
          <div className="flex" style={{ height: NEW_TRACK_ZONE_HEIGHT }}>
            <div
              data-track-header
              className="sticky left-0 z-20 shrink-0 border-r border-border bg-surface"
              style={{ width: HEADER_WIDTH }}
            />
            <div
              data-new-track-zone
              className={cn(
                'relative shrink-0 rounded-sm border border-dashed transition-colors',
                newTrackLaneKind || dropGhost?.laneId === NEW_TRACK_LANE ? 'border-primary bg-primary/10' : 'border-transparent',
              )}
              style={{ width: contentWidth, height: NEW_TRACK_ZONE_HEIGHT - ROW_GAP }}
            >
              {(newTrackLaneKind || dropGhost?.laneId === NEW_TRACK_LANE) && (
                <span className="pointer-events-none sticky left-2 inline-block px-2 text-[10px] leading-8 text-primary">
                  {t('dropToCreateTrack')}
                </span>
              )}
              {(laneContents.get(NEW_TRACK_LANE) ?? []).map((entry) => (
                <div
                  key={entry.element.id}
                  aria-hidden
                  className="pointer-events-none absolute top-1 h-6 rounded-sm bg-primary/50"
                  style={{ left: ticksToPx(entry.position.startTicks, zoom), width: Math.max(4, ticksToPx(entry.position.durationTicks, zoom)) }}
                />
              ))}
              {dropGhost && dropGhost.laneId === NEW_TRACK_LANE ? (
                <div
                  aria-hidden
                  className="pointer-events-none absolute top-1 h-6 rounded-sm border-2 border-dashed border-primary bg-primary/20"
                  style={{ left: ticksToPx(dropGhost.atTicks, zoom), width: Math.max(4, ticksToPx(dropGhost.durationTicks, zoom)) }}
                />
              ) : null}
            </div>
          </div>

          {/* Playhead line (below the ruler's own handle) */}
          <div
            aria-hidden
            className="pointer-events-none absolute z-20 w-px bg-danger"
            style={{ left: HEADER_WIDTH + playheadPx, top: RULER_HEIGHT, height: totalRowsHeight }}
          />
          {snapLine != null ? (
            <div
              aria-hidden
              className="pointer-events-none absolute z-20 w-px bg-accent"
              style={{ left: HEADER_WIDTH + ticksToPx(snapLine, zoom), top: RULER_HEIGHT, height: totalRowsHeight }}
            />
          ) : null}
          {dropGhost?.kind === 'files' ? (
            <div
              aria-hidden
              className="pointer-events-none absolute z-20 w-0.5 bg-primary"
              style={{ left: HEADER_WIDTH + ticksToPx(dropGhost.atTicks, zoom), top: RULER_HEIGHT, height: totalRowsHeight }}
            />
          ) : null}
          {marquee ? (
            <div
              aria-hidden
              className="pointer-events-none absolute z-30 border border-primary bg-primary/10"
              style={{
                left: HEADER_WIDTH + marquee.x0,
                top: marquee.y0,
                width: marquee.x1 - marquee.x0,
                height: marquee.y1 - marquee.y0,
              }}
            />
          ) : null}
        </div>
      </div>
    </div>
  );
}

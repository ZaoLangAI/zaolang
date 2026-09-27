'use client';

import { memo } from 'react';

import type { Marker } from '../engine/ports';
import { formatTimecode, rulerTicks, ticksToPx } from './geometry';

export const RULER_HEIGHT = 28;

/**
 * Time ruler: zoom-adaptive tick marks with `HH:MM:SS:FF` labels on the
 * majors, marker flags, and the playhead's grab handle. Scrubbing is wired
 * by the parent (pointer events bubble up from here), so this stays a pure
 * drawing component.
 */
export const Ruler = memo(function Ruler({
  zoom,
  fps,
  widthPx,
  visibleFromTicks,
  visibleToTicks,
  markers,
  playheadTicks,
  activeMarkerId,
  onMarkerClick,
}: {
  zoom: number;
  fps: number;
  widthPx: number;
  visibleFromTicks: number;
  visibleToTicks: number;
  markers: Marker[];
  playheadTicks: number;
  activeMarkerId: string | null;
  onMarkerClick: (marker: Marker) => void;
}) {
  const ticks = rulerTicks(zoom, visibleFromTicks, visibleToTicks);
  return (
    <div
      data-timeline-ruler
      className="relative select-none border-b border-border bg-surface text-[10px] text-muted"
      style={{ width: widthPx, height: RULER_HEIGHT }}
    >
      {ticks.map((tick) => {
        const x = ticksToPx(tick.ticks, zoom);
        return (
          <div
            key={tick.ticks}
            className="pointer-events-none absolute bottom-0"
            style={{ left: x }}
          >
            <div className={tick.major ? 'h-3 w-px bg-muted/70' : 'h-1.5 w-px bg-muted/40'} />
            {tick.major ? (
              <span className="absolute bottom-3.5 left-1 whitespace-nowrap tabular-nums leading-none">
                {formatTimecode(tick.ticks, fps)}
              </span>
            ) : null}
          </div>
        );
      })}
      {markers.map((marker) => (
        <button
          key={marker.id}
          type="button"
          data-marker-id={marker.id}
          title={marker.label ?? formatTimecode(marker.at_ticks, fps)}
          onPointerDown={(event) => event.stopPropagation()}
          onClick={(event) => {
            event.stopPropagation();
            onMarkerClick(marker);
          }}
          className={`absolute top-0 z-10 -translate-x-1/2 rounded-b px-1 text-[9px] leading-4 ${
            marker.id === activeMarkerId
              ? 'bg-primary text-white'
              : 'bg-accent/80 text-white hover:bg-accent'
          }`}
          style={{ left: ticksToPx(marker.at_ticks, zoom) }}
        >
          ▼
          {marker.label ? (
            <span className="ml-0.5 max-w-16 truncate align-top">{marker.label}</span>
          ) : null}
        </button>
      ))}
      <div
        data-playhead-handle
        className="absolute top-0 z-20 -translate-x-1/2 cursor-ew-resize"
        style={{ left: ticksToPx(playheadTicks, zoom) }}
      >
        <div className="h-3 w-3 rounded-b-sm bg-danger" />
        <div className="mx-auto h-4 w-px bg-danger" />
      </div>
    </div>
  );
});

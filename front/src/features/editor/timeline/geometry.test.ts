import { describe, expect, it } from 'vitest';

import { emptyDocument } from '../engine/canonical';
import { TICKS_PER_SECOND } from '../engine/ports';
import {
  BASE_PX_PER_SECOND,
  ZOOM_MAX,
  ZOOM_MIN,
  collectSnapTargets,
  edgeAutoScrollSpeed,
  elementIdsUnderTick,
  formatTimecode,
  frameTicks,
  pxPerTick,
  pxToTicks,
  rulerScale,
  rulerTicks,
  sliderFromZoom,
  snapTick,
  snapToFrame,
  wheelZoomFactor,
  zoomFromSlider,
  zoomToFit,
} from './geometry';

function clip(id: string, start: number, duration: number) {
  return {
    id,
    type: 'clip' as const,
    track_id: 'trk_video',
    asset_id: 'ast_1',
    start_ticks: start,
    duration_ticks: duration,
    source_in_ticks: 0,
    source_out_ticks: duration,
    volume_millipercent: 100_000,
    speed_millipercent: 100_000,
    text: null,
    caption_language: null,
    effects: [],
    mask: null,
    animations: { channels: {} },
    transition_in: null,
    transition_out: null,
  };
}

describe('zoom ↔ pixels', () => {
  it('maps one second to BASE_PX_PER_SECOND at zoom 1 and round-trips', () => {
    expect(pxPerTick(1) * TICKS_PER_SECOND).toBeCloseTo(BASE_PX_PER_SECOND);
    expect(pxToTicks(BASE_PX_PER_SECOND * 3, 1)).toBe(3 * TICKS_PER_SECOND);
  });

  it('wheel zoom is exponential, capped per notch and symmetric', () => {
    expect(wheelZoomFactor(-30)).toBeCloseTo(Math.exp(0.1));
    expect(wheelZoomFactor(-300)).toBeCloseTo(Math.exp(0.1));
    expect(wheelZoomFactor(30) * wheelZoomFactor(-30)).toBeCloseTo(1);
  });

  it('slider ↔ zoom round-trips across the exponential range', () => {
    expect(zoomFromSlider(0)).toBeCloseTo(ZOOM_MIN);
    expect(zoomFromSlider(1)).toBeCloseTo(ZOOM_MAX);
    expect(zoomFromSlider(sliderFromZoom(2.5))).toBeCloseTo(2.5);
  });

  it('zoomToFit puts the whole span inside the viewport', () => {
    const zoom = zoomToFit(20 * TICKS_PER_SECOND, 1000);
    expect(20 * TICKS_PER_SECOND * pxPerTick(zoom)).toBeLessThanOrEqual(1000);
    expect(20 * TICKS_PER_SECOND * pxPerTick(zoom)).toBeGreaterThan(900);
  });
});

describe('frames and timecode', () => {
  const canvas = { width: 1080, height: 1920, fps_num: 30, fps_den: 1 };

  it('derives frame length from fps and snaps to whole frames', () => {
    expect(frameTicks(canvas)).toBe(4000);
    expect(snapToFrame(4001, canvas)).toBe(4000);
    expect(snapToFrame(6001, canvas)).toBe(8000);
  });

  it('formats HH:MM:SS:FF and never shows a frame index at or above fps', () => {
    expect(formatTimecode(0, 30)).toBe('00:00:00:00');
    expect(formatTimecode(TICKS_PER_SECOND * 61 + 4000 * 12, 30)).toBe('00:01:01:12');
    expect(formatTimecode(TICKS_PER_SECOND - 1, 30)).toBe('00:00:00:29');
    expect(formatTimecode(3601 * TICKS_PER_SECOND, 25)).toBe('01:00:01:00');
  });
});

describe('ruler', () => {
  it('coarsens the interval as zoom decreases so labels never crowd', () => {
    const fine = rulerScale(4);
    const coarse = rulerScale(0.1);
    expect(fine.majorSeconds).toBeLessThan(coarse.majorSeconds);
    expect(fine.majorSeconds * BASE_PX_PER_SECOND * 4).toBeGreaterThanOrEqual(80);
  });

  it('emits major ticks on the interval boundary and minors in between', () => {
    const ticks = rulerTicks(1, 0, 2 * TICKS_PER_SECOND);
    const majors = ticks.filter((tick) => tick.major).map((tick) => tick.ticks);
    expect(majors[0]).toBe(0);
    expect(majors).toContain(rulerScale(1).majorSeconds * TICKS_PER_SECOND);
    expect(ticks.some((tick) => !tick.major)).toBe(true);
  });
});

describe('snapping', () => {
  it('snaps to the nearest target inside the threshold only', () => {
    expect(snapTick(1005, [1000, 2000], 10)).toEqual({ ticks: 1000, snapped: true, target: 1000 });
    expect(snapTick(1050, [1000, 2000], 10)).toEqual({ ticks: 1050, snapped: false, target: null });
  });

  it('collects 0, playhead, other elements’ edges and markers, excluding the dragged ids', () => {
    const document = emptyDocument();
    document.tracks[0]!.elements.push(clip('a', 1000, 500), clip('b', 3000, 500));
    document.markers.push({ id: 'm', at_ticks: 9000, label: null });
    const targets = collectSnapTargets(document, { excludeIds: ['a'], playheadTicks: 7000 });
    expect(targets).toEqual(expect.arrayContaining([0, 7000, 3000, 3500, 9000]));
    expect(targets).not.toContain(1000);
    expect(targets).not.toContain(1500);
  });
});

describe('elementIdsUnderTick', () => {
  it('returns only elements strictly containing the tick', () => {
    const document = emptyDocument();
    document.tracks[0]!.elements.push(clip('a', 0, 1000), clip('b', 1000, 1000));
    expect(elementIdsUnderTick(document, 500)).toEqual(['a']);
    expect(elementIdsUnderTick(document, 1000)).toEqual([]);
  });
});

describe('edgeAutoScrollSpeed', () => {
  it('scrolls backwards near the start edge, forwards near the end, otherwise not at all', () => {
    expect(edgeAutoScrollSpeed(10, 0, 1000)).toBeLessThan(0);
    expect(edgeAutoScrollSpeed(990, 0, 1000)).toBeGreaterThan(0);
    expect(edgeAutoScrollSpeed(500, 0, 1000)).toBe(0);
    expect(Math.abs(edgeAutoScrollSpeed(0, 0, 1000))).toBe(15);
  });
});

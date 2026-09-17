/**
 * Dialogue ducking: turn a music track down while anyone speaks. Pure — it
 * only reads the timeline and returns ordinary `clear_keyframes` +
 * `set_keyframe` (`volume`) commands, so the result is a normal, undoable
 * edit that preview and export both play through `resolveAudioLayers`.
 *
 * "Speech" is every clip on the other unmuted audio tracks. Nearby lines
 * are merged so the music doesn't bob back up between two sentences. Each
 * music clip's existing volume keyframes are replaced.
 */

import { TICKS_PER_SECOND, type EditCommand, type TimelineTrack } from './ports';

export interface DuckingOptions {
  /** Music level while speech plays, as a fraction of the clip's own volume. */
  duckRatio: number;
  /** Fade down this long before a line starts … */
  attackTicks: number;
  /** … and back up this long after it ends. */
  releaseTicks: number;
}

export const DEFAULT_DUCKING: DuckingOptions = {
  duckRatio: 0.25,
  attackTicks: Math.round(TICKS_PER_SECOND * 0.2),
  releaseTicks: Math.round(TICKS_PER_SECOND * 0.5),
};

const MAX_KEYFRAMES_PER_CHANNEL = 64;
const MAX_COMMANDS_PER_BATCH = 100;

export interface DuckingPlan {
  commands: EditCommand[];
  /** Some speech was left unducked to stay within the keyframe or batch caps. */
  truncated: boolean;
}

type Span = [start: number, end: number];

/** Speech spans on every unmuted audio track except `musicTrackId`, merged
 * when the gap between them is shorter than a fade down plus a fade up. */
export function speechSpans(
  tracks: readonly TimelineTrack[],
  musicTrackId: string,
  options: DuckingOptions = DEFAULT_DUCKING,
): Span[] {
  const spans: Span[] = tracks
    .filter((track) => track.kind === 'audio' && !track.muted && track.id !== musicTrackId)
    .flatMap((track) => track.elements)
    .filter((element) => element.asset_id && element.duration_ticks > 0)
    .map((element): Span => [element.start_ticks, element.start_ticks + element.duration_ticks])
    .sort((a, b) => a[0] - b[0]);
  const merged: Span[] = [];
  const bridge = options.attackTicks + options.releaseTicks;
  for (const span of spans) {
    const last = merged[merged.length - 1];
    if (last && span[0] <= last[1] + bridge) last[1] = Math.max(last[1], span[1]);
    else merged.push([span[0], span[1]]);
  }
  return merged;
}

interface Point {
  at: number;
  value: number;
}

/** Keyframes for one music clip over `[clipStart, clipEnd)`. A span that
 * starts before the clip needs no fade down, one that outlasts it no fade
 * up; later points at the same tick win. */
function clipPoints(
  clipStart: number,
  clipEnd: number,
  base: number,
  spans: Span[],
  options: DuckingOptions,
): { points: Point[]; truncated: boolean } {
  const ducked = Math.round(base * options.duckRatio);
  const byTick = new Map<number, number>();
  let truncated = false;
  for (const [start, end] of spans) {
    if (end <= clipStart || start >= clipEnd) continue;
    const next = new Map(byTick);
    if (start > clipStart) next.set(Math.max(clipStart, start - options.attackTicks), base);
    next.set(Math.max(clipStart, start), ducked);
    next.set(Math.min(clipEnd, end), ducked);
    if (end < clipEnd) next.set(Math.min(clipEnd, end + options.releaseTicks), base);
    if (next.size > MAX_KEYFRAMES_PER_CHANNEL) {
      truncated = true;
      break;
    }
    for (const [at, value] of next) byTick.set(at, value);
  }
  const points = [...byTick].map(([at, value]) => ({ at, value })).sort((a, b) => a.at - b.at);
  return { points, truncated };
}

export function buildDuckingCommands(
  tracks: readonly TimelineTrack[],
  musicTrackId: string,
  options: DuckingOptions = DEFAULT_DUCKING,
): DuckingPlan {
  const music = tracks.find((track) => track.id === musicTrackId);
  if (!music || music.kind !== 'audio') return { commands: [], truncated: false };
  const spans = speechSpans(tracks, musicTrackId, options);
  const commands: EditCommand[] = [];
  let truncated = false;
  for (const element of music.elements) {
    if (!element.asset_id) continue;
    const clipEnd = element.start_ticks + element.duration_ticks;
    const plan = clipPoints(element.start_ticks, clipEnd, element.volume_millipercent, spans, options);
    truncated ||= plan.truncated;
    if (plan.points.length === 0) continue;
    if (commands.length + 1 + plan.points.length > MAX_COMMANDS_PER_BATCH) {
      truncated = true;
      break;
    }
    commands.push({ type: 'clear_keyframes', element_id: element.id, property: 'volume' });
    for (const point of plan.points) {
      commands.push({
        type: 'set_keyframe',
        element_id: element.id,
        property: 'volume',
        at_ticks: point.at,
        value: point.value,
        easing: 'linear',
      });
    }
  }
  return { commands, truncated };
}

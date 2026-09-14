import { describe, expect, it } from 'vitest';

import { buildDuckingCommands, DEFAULT_DUCKING, speechSpans } from './ducking';
import type { EditCommand, TimelineElement, TimelineTrack } from './ports';
import { TICKS_PER_SECOND } from './ports';

const S = TICKS_PER_SECOND;

function element(id: string, startSeconds: number, seconds: number, volume = 100_000): TimelineElement {
  return {
    id,
    type: 'clip',
    track_id: 'trk',
    asset_id: `ast_${id}`,
    start_ticks: startSeconds * S,
    duration_ticks: seconds * S,
    source_in_ticks: 0,
    source_out_ticks: seconds * S,
    volume_millipercent: volume,
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

function audioTrack(id: string, elements: TimelineElement[], muted = false): TimelineTrack {
  return { id, kind: 'audio', elements, order: 0, label: null, muted };
}

function keyframes(commands: EditCommand[], elementId: string): Array<[number, number]> {
  return commands.flatMap((command) =>
    command.type === 'set_keyframe' && command.element_id === elementId
      ? [[command.at_ticks / S, command.value] as [number, number]]
      : [],
  );
}

describe('speechSpans', () => {
  it('merges lines closer than a fade down plus a fade up and skips muted tracks', () => {
    const tracks = [
      audioTrack('trk_music', [element('m', 0, 20)]),
      audioTrack('trk_voice', [element('a', 2, 2), element('b', 4.5, 1.5), element('c', 10, 2)]),
      audioTrack('trk_muted', [element('x', 15, 2)], true),
    ];
    expect(speechSpans(tracks, 'trk_music')).toEqual([
      [2 * S, 6 * S],
      [10 * S, 12 * S],
    ]);
  });
});

describe('buildDuckingCommands', () => {
  it('ducks the music under each speech span with a fade down and back up', () => {
    const tracks = [
      audioTrack('trk_music', [element('m', 0, 20)]),
      audioTrack('trk_voice', [element('a', 2, 2), element('b', 4.5, 1.5), element('c', 10, 2)]),
    ];
    const plan = buildDuckingCommands(tracks, 'trk_music');
    expect(plan.truncated).toBe(false);
    expect(plan.commands[0]).toEqual({ type: 'clear_keyframes', element_id: 'm', property: 'volume' });
    expect(keyframes(plan.commands, 'm')).toEqual([
      [1.8, 100_000],
      [2, 25_000],
      [6, 25_000],
      [6.5, 100_000],
      [9.8, 100_000],
      [10, 25_000],
      [12, 25_000],
      [12.5, 100_000],
    ]);
  });

  it('starts ducked when speech is already playing as the music enters, and stays down to its end', () => {
    const tracks = [
      audioTrack('trk_music', [element('m', 3, 5, 80_000)]),
      audioTrack('trk_voice', [element('a', 0, 4), element('b', 7, 3)]),
    ];
    expect(keyframes(buildDuckingCommands(tracks, 'trk_music').commands, 'm')).toEqual([
      [3, 20_000],
      [4, 20_000],
      [4.5, 80_000],
      [6.8, 80_000],
      [7, 20_000],
      [8, 20_000],
    ]);
  });

  it('does nothing without speech or on a non-audio track', () => {
    const music = audioTrack('trk_music', [element('m', 0, 10)]);
    expect(buildDuckingCommands([music], 'trk_music').commands).toEqual([]);
    expect(buildDuckingCommands([music], 'trk_missing').commands).toEqual([]);
  });

  it('stays within the 64-keyframe channel cap and says so', () => {
    const lines = Array.from({ length: 30 }, (_, index) => element(`l${index}`, index * 3, 1));
    const tracks = [audioTrack('trk_music', [element('m', 0, 100)]), audioTrack('trk_voice', lines)];
    const plan = buildDuckingCommands(tracks, 'trk_music', DEFAULT_DUCKING);
    expect(plan.truncated).toBe(true);
    expect(keyframes(plan.commands, 'm').length).toBeLessThanOrEqual(64);
  });
});

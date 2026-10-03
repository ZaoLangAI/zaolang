import { describe, expect, it } from 'vitest';

import { jobStageState, stoppedTitleKey } from './job-stage-state';

const ev = (...types: string[]) => types.map((event_type) => ({ event_type }));

describe('jobStageState', () => {
  it('advances to the first stage the events have not reached', () => {
    expect(jobStageState('running', ev('queued', 'safety')).displayStage).toBe('planning');
  });

  it('lights every stage on success even when the events were sparse', () => {
    // A provider that never emitted a `quality` event still passed through it;
    // leaving that dot dark on a finished job reads as a failure.
    const state = jobStageState('succeeded', ev('queued'));
    expect(state.displayStage).toBe('done');
    expect(state.reached.size).toBeGreaterThan(1);
    expect(state.reached.has('quality')).toBe(true);
  });

  it('shows how far a failed job got, not where it was going', () => {
    const state = jobStageState('failed', ev('queued', 'safety', 'planning'));
    expect(state.displayStage).toBe('planning');
    expect(state.finished).toBe(true);
  });

  it('falls back to queued when a job failed before any event landed', () => {
    expect(jobStageState('failed', []).displayStage).toBe('queued');
  });

  it('parks on planning while awaiting input', () => {
    // The follow-up question is raised from the planning node. Showing the
    // next unreached stage would claim progress that is waiting on the user.
    const state = jobStageState('awaiting_input', ev('queued', 'safety', 'planning'));
    expect(state.displayStage).toBe('planning');
    expect(state.awaitingInput).toBe(true);
    expect(state.finished).toBe(false);
  });

  it('ignores event types that map to no stage', () => {
    // `thinking` frames arrive over Redis only and must not light a dot —
    // they are deliberately absent from `STAGE_FOR_EVENT`.
    expect(jobStageState('running', ev('thinking')).reached.size).toBe(0);
  });

  it('reports a stable key for the stages reached', () => {
    // The `Set` gets a new identity every render; an animation effect keyed on
    // it would re-fire forever.
    const a = jobStageState('running', ev('queued', 'safety'));
    const b = jobStageState('running', ev('safety', 'queued'));
    expect(a.reachedKey).toBe(b.reachedKey);
  });

  it('treats every terminal status as finished', () => {
    for (const status of ['succeeded', 'failed', 'cancelled', 'expired']) {
      expect(jobStageState(status, []).finished).toBe(true);
    }
    for (const status of ['queued', 'running', 'awaiting_input']) {
      expect(jobStageState(status, []).finished).toBe(false);
    }
  });
});

describe('stoppedTitleKey', () => {
  it('titles a job that stopped without a result, and nothing else', () => {
    expect(stoppedTitleKey('failed')).toBe('failedTitle');
    expect(stoppedTitleKey('expired')).toBe('failedTitle');
    expect(stoppedTitleKey('cancelled')).toBe('cancelledTitle');
    expect(stoppedTitleKey('running')).toBeNull();
    expect(stoppedTitleKey('succeeded')).toBeNull();
  });
});

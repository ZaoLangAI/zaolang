import { describe, expect, it } from 'vitest';

import { isJobInFlight, studioSubmitBusy, studioSubmitLabelKey } from './studio-submit-busy';

describe('isJobInFlight', () => {
  it.each(['created', 'queued', 'submitted', 'running', 'awaiting_input'] as const)(
    'treats %s as in flight',
    (status) => {
      expect(isJobInFlight(status)).toBe(true);
    },
  );

  it.each(['succeeded', 'failed', 'cancelled', 'expired'] as const)(
    'treats %s as terminal',
    (status) => {
      expect(isJobInFlight(status)).toBe(false);
    },
  );

  it('ignores a missing status', () => {
    expect(isJobInFlight(undefined)).toBe(false);
    expect(isJobInFlight(null)).toBe(false);
    expect(isJobInFlight('')).toBe(false);
  });
});

describe('studioSubmitBusy', () => {
  it('prefers the HTTP submit over polish and an in-flight job', () => {
    expect(
      studioSubmitBusy({
        submitting: true,
        polishPending: true,
        jobs: [{ status: 'running' }],
      }),
    ).toBe('submitting');
  });

  it('locks on polish while no submit is in flight', () => {
    expect(
      studioSubmitBusy({
        submitting: false,
        polishPending: true,
        jobs: [{ status: 'succeeded' }],
      }),
    ).toBe('polishing');
  });

  it.each(['queued', 'running', 'awaiting_input'] as const)('locks while a job is %s', (status) => {
    expect(
      studioSubmitBusy({
        submitting: false,
        polishPending: false,
        jobs: [{ status }],
      }),
    ).toBe('generating');
  });

  it('stays idle once every job is terminal', () => {
    expect(
      studioSubmitBusy({
        submitting: false,
        polishPending: false,
        jobs: [{ status: 'succeeded' }, { status: 'failed' }, { status: 'cancelled' }],
      }),
    ).toBeNull();
  });

  it('still locks when the previewed version succeeded but another job is running', () => {
    expect(
      studioSubmitBusy({
        submitting: false,
        polishPending: false,
        jobs: [{ status: 'succeeded' }, { status: 'running' }],
      }),
    ).toBe('generating');
  });

  it('maps each busy reason onto the matching remixPage key', () => {
    expect(studioSubmitLabelKey('submitting')).toBe('submitting');
    expect(studioSubmitLabelKey('polishing')).toBe('submitPolishing');
    expect(studioSubmitLabelKey('generating')).toBe('submitGenerating');
    expect(studioSubmitLabelKey(null)).toBe('submit');
  });

  it('ignores null slots in the job list', () => {
    expect(
      studioSubmitBusy({
        submitting: false,
        polishPending: false,
        jobs: [null, undefined, { status: 'expired' }],
      }),
    ).toBeNull();
  });
});

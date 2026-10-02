import { describe, expect, it } from 'vitest';

import { fillStep } from './fill';

describe('fillStep', () => {
  it('runs the wave the backend just submitted', () => {
    expect(fillStep({ submitted_job_id: 'job_1', submitted_slots: ['portrait'] }, null)).toEqual({
      kind: 'running',
      jobId: 'job_1',
      slots: ['portrait'],
    });
  });

  it('is done when nothing was left to submit', () => {
    expect(fillStep({ submitted_job_id: null, submitted_slots: [] }, ['expressions'])).toEqual({
      kind: 'done',
    });
  });

  it('stops when the same wave comes back after it succeeded', () => {
    expect(
      fillStep({ submitted_job_id: 'job_2', submitted_slots: ['front', 'side'] }, [
        'front',
        'side',
      ]),
    ).toEqual({ kind: 'stuck', slots: ['front', 'side'] });
  });

  it('continues with a narrower wave after a partial delivery', () => {
    expect(
      fillStep({ submitted_job_id: 'job_3', submitted_slots: ['back'] }, ['front', 'side', 'back'])
        .kind,
    ).toBe('running');
  });
});

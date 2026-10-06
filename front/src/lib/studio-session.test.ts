import { describe, expect, it } from 'vitest';

import { studioSessionKey } from './studio-session';

describe('studioSessionKey', () => {
  it('keys a draft-card resume on draft id alone', () => {
    expect(
      studioSessionKey({
        draftId: 'drf_clip1',
        mode: 'video_creation',
        videoAssetKind: 'character_action',
        subjectNameHint: '角色2',
      }),
    ).toBe('draft:drf_clip1');
  });

  it('remounts when a notification points at a different job on the same draft', () => {
    expect(
      studioSessionKey({ draftId: 'drf_clip1', jobId: 'job_failed', mode: 'video_creation' }),
    ).toBe('draft:drf_clip1|job:job_failed');
    expect(
      studioSessionKey({ draftId: 'drf_clip1', jobId: 'job_retry', mode: 'video_creation' }),
    ).toBe('draft:drf_clip1|job:job_retry');
  });

  it('changes when the notification points at a different draft', () => {
    expect(studioSessionKey({ draftId: 'drf_clip1', mode: 'video_creation' })).not.toBe(
      studioSessionKey({ draftId: 'drf_clip2', mode: 'video_creation' }),
    );
  });

  it('distinguishes two script breakpoints that share the pathname', () => {
    const first = studioSessionKey({ mode: 'video_creation', linkBreakpointKey: '内景#1' });
    const second = studioSessionKey({ mode: 'video_creation', linkBreakpointKey: '内景#2' });
    expect(first).toBe('fresh|video_creation|内景#1');
    expect(first).not.toBe(second);
  });

  it('distinguishes two character-action jump-outs', () => {
    const one = studioSessionKey({
      mode: 'video_creation',
      videoAssetKind: 'character_action',
      targetCharacterId: 'sk_one',
    });
    const two = studioSessionKey({
      mode: 'video_creation',
      videoAssetKind: 'character_action',
      targetCharacterId: 'sk_two',
    });
    expect(one).not.toBe(two);
  });

  it('distinguishes two plaza skill deep-links that share the pathname', () => {
    const orbit = studioSessionKey({ mode: 'video_creation', skillId: 'sk_orbit' });
    const crash = studioSessionKey({ mode: 'video_creation', skillId: 'sk_crash' });
    expect(orbit).not.toBe(crash);
    expect(orbit).toContain('sk_orbit');
  });

  it('differs between a fresh session and a draftId resume', () => {
    expect(studioSessionKey({ mode: 'video_creation', subjectNameHint: '角色2' })).not.toBe(
      studioSessionKey({ draftId: 'drf_clip1', mode: 'video_creation' }),
    );
  });
});

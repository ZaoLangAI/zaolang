import { describe, expect, it } from 'vitest';

import {
  draftReturnParams,
  readDraftReturnContext,
  sanitizeReturnTo,
  studioSessionKey,
} from './studio-session';

describe('studioSessionKey', () => {
  it('keys a draft-card resume on draft id alone', () => {
    expect(
      studioSessionKey({
        draftId: 'drf_char1',
        mode: 'image_creation',
        assetKind: 'character',
        subjectNameHint: '角色2',
      }),
    ).toBe('draft:drf_char1');
  });

  it('remounts when a notification points at a different job on the same draft', () => {
    expect(
      studioSessionKey({
        draftId: 'drf_char1',
        jobId: 'job_failed',
        mode: 'image_creation',
      }),
    ).toBe('draft:drf_char1|job:job_failed');
    expect(
      studioSessionKey({
        draftId: 'drf_char1',
        jobId: 'job_retry',
        mode: 'image_creation',
      }),
    ).toBe('draft:drf_char1|job:job_retry');
  });

  it('changes when the notification points at a different draft', () => {
    const characterTwo = studioSessionKey({
      draftId: 'drf_char2',
      mode: 'image_creation',
    });
    const characterOne = studioSessionKey({
      draftId: 'drf_char1',
      mode: 'image_creation',
    });
    expect(characterOne).not.toBe(characterTwo);
  });

  it('distinguishes two script jump-outs that share the pathname', () => {
    const characterOne = studioSessionKey({
      mode: 'image_creation',
      assetKind: 'character',
      subjectNameHint: '角色1',
    });
    const characterTwo = studioSessionKey({
      mode: 'image_creation',
      assetKind: 'character',
      subjectNameHint: '角色2',
    });
    expect(characterOne).toBe('fresh|image_creation|character|角色1');
    expect(characterTwo).toBe('fresh|image_creation|character|角色2');
    expect(characterOne).not.toBe(characterTwo);
  });

  it('differs between a fresh script jump-out and a draftId resume', () => {
    expect(
      studioSessionKey({
        mode: 'image_creation',
        assetKind: 'character',
        subjectNameHint: '角色2',
      }),
    ).not.toBe(
      studioSessionKey({
        draftId: 'drf_char1',
        mode: 'image_creation',
      }),
    );
  });
});

describe('sanitizeReturnTo', () => {
  it('keeps a script-studio path', () => {
    expect(sanitizeReturnTo('/create/script/ep_1')).toBe('/create/script/ep_1');
  });

  it('rejects anything outside the script-studio whitelist', () => {
    expect(sanitizeReturnTo('https://evil.example/create/script/ep_1')).toBeUndefined();
    expect(sanitizeReturnTo('/create/new')).toBeUndefined();
    expect(sanitizeReturnTo('//evil.example')).toBeUndefined();
    expect(sanitizeReturnTo(undefined)).toBeUndefined();
  });
});

describe('readDraftReturnContext', () => {
  it('restores the jump-back trio from a draft written by the studio', () => {
    expect(
      readDraftReturnContext({
        return_to: '/create/script/ep_1',
        return_link_kind: 'character',
        return_link_label: '角色1',
      }),
    ).toEqual({
      returnTo: '/create/script/ep_1',
      returnLinkKind: 'character',
      returnLinkLabel: '角色1',
    });
  });

  it('drops a return_to that is not a script-studio path', () => {
    expect(
      readDraftReturnContext({
        return_to: 'https://evil.example/',
        return_link_kind: 'character',
        return_link_label: '角色1',
      }),
    ).toEqual({
      returnTo: undefined,
      returnLinkKind: 'character',
      returnLinkLabel: '角色1',
    });
  });

  it('ignores an unknown link kind and a non-object params blob', () => {
    expect(readDraftReturnContext({ return_link_kind: 'cover' })).toEqual({
      returnTo: undefined,
      returnLinkKind: undefined,
      returnLinkLabel: undefined,
    });
    expect(readDraftReturnContext(null)).toEqual({});
    expect(readDraftReturnContext(['/create/script/ep_1'])).toEqual({});
  });
});

describe('draftReturnParams', () => {
  it('writes snake_case keys only when the path is whitelisted', () => {
    expect(
      draftReturnParams({
        returnTo: '/create/script/ep_1',
        returnLinkKind: 'character',
        returnLinkLabel: '角色1',
      }),
    ).toEqual({
      return_to: '/create/script/ep_1',
      return_link_kind: 'character',
      return_link_label: '角色1',
    });
    expect(draftReturnParams({ returnTo: '/create/new' })).toBeUndefined();
    expect(draftReturnParams({})).toBeUndefined();
  });
});

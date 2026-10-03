import { describe, expect, it } from 'vitest';

import {
  draftReturnParams,
  readDraftReturnContext,
  resumedTargetCard,
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

  it('distinguishes two plaza skill deep-links that share the pathname', () => {
    const turnaround = studioSessionKey({
      mode: 'image_creation',
      assetKind: 'character',
      skillId: 'sk_turnaround',
    });
    const cover = studioSessionKey({
      mode: 'image_creation',
      assetKind: 'cover',
      skillId: 'sk_cover',
    });
    expect(turnaround).not.toBe(cover);
    expect(turnaround).toContain('sk_turnaround');
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

  it('keeps the character-library path by exact match', () => {
    expect(sanitizeReturnTo('/create/characters')).toBe('/create/characters');
  });

  it('keeps the scene-library path by exact match', () => {
    expect(sanitizeReturnTo('/create/scenes')).toBe('/create/scenes');
  });

  it('rejects anything outside the script-studio and library whitelist', () => {
    expect(sanitizeReturnTo('https://evil.example/create/script/ep_1')).toBeUndefined();
    expect(sanitizeReturnTo('/create/new')).toBeUndefined();
    expect(sanitizeReturnTo('/create/characters/evil')).toBeUndefined();
    expect(sanitizeReturnTo('/create/characters?x=1')).toBeUndefined();
    expect(sanitizeReturnTo('/create/scenes/evil')).toBeUndefined();
    expect(sanitizeReturnTo('/create/scenes?x=1')).toBeUndefined();
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

  it('restores a character-library jump-back', () => {
    expect(
      readDraftReturnContext({
        return_to: '/create/characters',
      }),
    ).toEqual({
      returnTo: '/create/characters',
      returnLinkKind: undefined,
      returnLinkLabel: undefined,
    });
  });

  it('restores a scene-library jump-back', () => {
    expect(
      readDraftReturnContext({
        return_to: '/create/scenes',
      }),
    ).toEqual({
      returnTo: '/create/scenes',
      returnLinkKind: undefined,
      returnLinkLabel: undefined,
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
    expect(
      draftReturnParams({
        returnTo: '/create/characters',
      }),
    ).toEqual({
      return_to: '/create/characters',
    });
    expect(
      draftReturnParams({
        returnTo: '/create/scenes',
      }),
    ).toEqual({
      return_to: '/create/scenes',
    });
    expect(draftReturnParams({ returnTo: '/create/new' })).toBeUndefined();
    expect(draftReturnParams({})).toBeUndefined();
  });
});

describe('studioSessionKey and the identity portrait', () => {
  it("keeps a portrait jump-out apart from the same card's sheet jump-out", () => {
    const sheet = studioSessionKey({ mode: 'image_creation', targetCharacterId: 'skl_char' });
    const portrait = studioSessionKey({
      mode: 'image_creation',
      targetCharacterId: 'skl_char',
      characterPortrait: '1',
    });
    expect(portrait).not.toBe(sheet);
  });
});

describe('resumedTargetCard', () => {
  it('re-targets the card a resumed job filed into, by its asset kind', () => {
    expect(resumedTargetCard({ asset_kind: 'scene', linked_scene_id: 'sk_s' })).toEqual({
      characterId: null,
      sceneId: 'sk_s',
    });
    expect(
      resumedTargetCard({
        asset_kind: 'character',
        linked_character_id: 'sk_c',
        linked_scene_id: 'x',
      }),
    ).toEqual({ characterId: 'sk_c', sceneId: null });
    expect(resumedTargetCard({ asset_kind: 'general', linked_scene_id: 'sk_s' })).toEqual({
      characterId: null,
      sceneId: null,
    });
  });
});

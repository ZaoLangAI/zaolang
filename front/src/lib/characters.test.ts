import { describe, expect, it } from 'vitest';

import type { AssetEntry, AssetVariant, GenerationJob } from '@/lib/api/types';

import {
  borrowedCharacterReferences,
  CHARACTER_SHEET_PROMPT_HINT,
  characterImageStudioHref,
  characterSheetAsset,
  characterSheetPrompt,
  defaultCharacterReferenceIds,
  findCompletionJobFor,
  isCharacterCompletionJob,
} from './characters';
import type { Character } from '@/lib/api/types';

function job(overrides: Partial<GenerationJob>): GenerationJob {
  return {
    id: 'job_front',
    status: 'succeeded',
    operation: 'text_to_image',
    quality_tier: 'standard',
    progress: 100,
    quoted_credits: 12,
    reserved_credits: 12,
    requested_outputs: 1,
    estimated_seconds: 10,
    candidate_entries: 0,
    cancel_requested: false,
    created_at: '2026-08-30T00:00:00Z',
    asset_kind: 'character',
    ...overrides,
  };
}

describe('characterSheetPrompt', () => {
  it('joins name, appearance and the sheet-layout hint', () => {
    expect(characterSheetPrompt({ name: '林深', appearance: '银发风衣' })).toBe(
      `林深。银发风衣。${CHARACTER_SHEET_PROMPT_HINT}`,
    );
  });

  it('falls back to the name alone when there is no appearance', () => {
    expect(characterSheetPrompt({ name: '林深' })).toBe(`林深。${CHARACTER_SHEET_PROMPT_HINT}`);
  });

  it('does not stack a second period when appearance already ends with one', () => {
    expect(characterSheetPrompt({ name: '林野', appearance: '银发风衣。' })).toBe(
      `林野。银发风衣。${CHARACTER_SHEET_PROMPT_HINT}`,
    );
  });
});

describe('characterImageStudioHref', () => {
  it('opens on the identity portrait with identity text and no sheet layout', () => {
    const href = characterImageStudioHref({
      characterId: 'skl_char',
      name: '林深',
      appearance: '银发风衣',
      portrait: true,
    });
    const url = new URL(href, 'https://example.test');
    expect(url.searchParams.get('characterPortrait')).toBe('1');
    expect(url.searchParams.get('prompt')).toBe('林深。银发风衣');
  });

  it('targets the image studio with the character sheet query', () => {
    const href = characterImageStudioHref({
      characterId: 'skl_char',
      name: '林深',
      appearance: '银发风衣',
    });
    const url = new URL(href, 'https://example.test');
    expect(url.pathname).toBe('/create/new');
    expect(url.searchParams.get('mode')).toBe('image_creation');
    expect(url.searchParams.get('assetKind')).toBe('character');
    expect(url.searchParams.get('targetCharacterId')).toBe('skl_char');
    expect(url.searchParams.get('subjectNameHint')).toBe('林深');
    expect(url.searchParams.get('returnTo')).toBe('/create/characters');
    expect(url.searchParams.get('prompt')).toContain('银发风衣');
    expect(url.searchParams.get('prompt')).toContain('设定图');
  });
});

describe('characterSheetAsset', () => {
  it('prefers the front-tagged asset, else the first one', () => {
    const character = {
      reference_assets: [
        { asset_id: 'ast_side', view: 'side', url: 'https://cdn/side.png' },
        { asset_id: 'ast_front', view: 'front', url: 'https://cdn/front.png' },
      ],
    } as Character;
    expect(characterSheetAsset(character)?.asset_id).toBe('ast_front');
    expect(
      characterSheetAsset({
        reference_assets: [{ asset_id: 'ast_any', view: 'general', url: 'https://cdn/any.png' }],
      } as Character)?.asset_id,
    ).toBe('ast_any');
  });
});

describe('isCharacterCompletionJob', () => {
  it('is a character job whose views omit front', () => {
    expect(isCharacterCompletionJob(job({ character_views: ['side', 'back'] }))).toBe(true);
    expect(isCharacterCompletionJob(job({ character_views: ['front'] }))).toBe(false);
    expect(isCharacterCompletionJob(job({ asset_kind: 'scene' }))).toBe(false);
  });
});

describe('findCompletionJobFor', () => {
  const front = job({
    id: 'job_front',
    linked_character_id: 'skl_char',
    character_views: ['front'],
    created_at: '2026-08-30T00:00:00Z',
  });

  it('returns an in-flight completion in the same window', () => {
    const completing = job({
      id: 'job_side',
      status: 'running',
      linked_character_id: 'skl_char',
      character_views: ['side', 'back'],
      created_at: '2026-08-30T00:01:00Z',
    });
    expect(findCompletionJobFor([front, completing], front)?.id).toBe('job_side');
  });

  it('ignores a failed or cancelled completion so the button can be offered again', () => {
    const failed = job({
      id: 'job_failed',
      status: 'failed',
      linked_character_id: 'skl_char',
      character_views: ['side', 'back'],
      created_at: '2026-08-30T00:01:00Z',
    });
    const cancelled = job({
      id: 'job_cancelled',
      status: 'cancelled',
      linked_character_id: 'skl_char',
      character_views: ['side', 'back'],
      created_at: '2026-08-30T00:02:00Z',
    });
    expect(findCompletionJobFor([front, failed, cancelled], front)).toBeNull();
  });

  it('prefers a later succeeded completion over an earlier failed one', () => {
    const failed = job({
      id: 'job_failed',
      status: 'failed',
      linked_character_id: 'skl_char',
      character_views: ['side', 'back'],
      created_at: '2026-08-30T00:01:00Z',
    });
    const succeeded = job({
      id: 'job_ok',
      status: 'succeeded',
      linked_character_id: 'skl_char',
      character_views: ['side', 'back'],
      created_at: '2026-08-30T00:02:00Z',
    });
    expect(findCompletionJobFor([front, failed, succeeded], front)?.id).toBe('job_ok');
  });
});

describe('referenceByView', () => {
  it('prefers the default look over a named outfit for the same view', () => {
    const character = {
      reference_assets: [
        { asset_id: 'ast_wedding', view: 'front', label: '婚礼', url: 'https://cdn/w.png' },
        { asset_id: 'ast_daily', view: 'front', label: null, url: 'https://cdn/d.png' },
      ],
    } as Character;
    expect(characterSheetAsset(character)?.asset_id).toBe('ast_daily');
  });

  it('falls back to a named outfit when it is the only one for that view', () => {
    const character = {
      reference_assets: [
        { asset_id: 'ast_wedding', view: 'front', label: '婚礼', url: 'https://cdn/w.png' },
      ],
    } as Character;
    expect(characterSheetAsset(character)?.asset_id).toBe('ast_wedding');
  });
});

describe('defaultCharacterReferenceIds', () => {
  it('sends the unnamed sheet views in front/side/back order', () => {
    const character = {
      reference_assets: [
        { asset_id: 'back', view: 'back', label: null },
        { asset_id: 'wedding', view: 'front', label: '婚礼' },
        { asset_id: 'grid', view: 'general', label: '表情·冷笑' },
        { asset_id: 'front', view: 'front', label: null },
      ],
    } as Character;
    expect(defaultCharacterReferenceIds(character)).toEqual(['front', 'back']);
  });

  it('leads with an identity-portrait anchor, then the default look’s sheet and views', () => {
    const entry = (id: string, entry_type: AssetEntry['entry_type'], view?: string) =>
      ({ id, asset_id: id, entry_type, view, status: 'approved' }) as AssetEntry;
    const look = (id: string, is_default: boolean, entries: AssetEntry[]) =>
      ({ id, name: id, is_default, sort_order: 0, entries }) as AssetVariant;
    const defaultLook = look('default', true, [
      entry('back', 'view', 'back'),
      entry('smile', 'expression_sheet'),
      entry('portrait', 'identity_portrait'),
      entry('side', 'view', 'side'),
      { ...entry('old_sheet', 'character_sheet'), status: 'candidate' } as AssetEntry,
      entry('sheet', 'character_sheet', 'front'),
    ]);
    const wedding = look('wedding', false, [entry('wedding_sheet', 'character_sheet', 'front')]);

    expect(
      defaultCharacterReferenceIds({
        looks: [defaultLook, wedding],
        anchor_entry_id: 'portrait',
      } as Character),
    ).toEqual(['portrait', 'sheet', 'side']);
    // A sheet anchor in another look never leads; the default look's own does.
    expect(
      defaultCharacterReferenceIds({
        looks: [defaultLook, wedding],
        anchor_entry_id: 'wedding_sheet',
      } as Character),
    ).toEqual(['sheet', 'side', 'back']);
  });

  it('falls back to unlabelled uploads, then to anything', () => {
    expect(
      defaultCharacterReferenceIds({
        reference_assets: [
          { asset_id: 'a', view: 'general', label: '婚礼' },
          { asset_id: 'b', view: 'general', label: null },
        ],
      } as Character),
    ).toEqual(['b']);
    expect(
      defaultCharacterReferenceIds({
        reference_assets: [{ asset_id: 'a', view: 'general', label: '婚礼' }],
      } as Character),
    ).toEqual(['a']);
  });
});

function entry(id: string, entry_type: AssetEntry['entry_type'], status = 'approved'): AssetEntry {
  return { id, asset_id: id, entry_type, status, is_anchor: false } as AssetEntry;
}

function look(id: string, is_default: boolean, entries: AssetEntry[]): AssetVariant {
  return { id, name: id, is_default, sort_order: 0, entries } as AssetVariant;
}

describe('borrowedCharacterReferences', () => {
  const portrait = entry('portrait', 'identity_portrait');
  const sheet = entry('sheet', 'character_sheet');
  const outfit = entry('outfit', 'outfit_detail');

  it('is the approved portrait for the default look, nothing without one', () => {
    const withPortrait = { looks: [look('default', true, [portrait, sheet])] } as Character;
    expect(borrowedCharacterReferences(withPortrait).map((e) => e.id)).toEqual(['portrait']);
    const candidateOnly = {
      looks: [look('default', true, [entry('p2', 'identity_portrait', 'candidate'), sheet])],
    } as Character;
    expect(borrowedCharacterReferences(candidateOnly)).toEqual([]);
  });

  it('adds the look’s own sheet and outfit references for a 换装', () => {
    const character = {
      looks: [
        look('default', true, [portrait, sheet]),
        look('wedding', false, [entry('wedding_sheet', 'character_sheet'), outfit]),
      ],
    } as Character;
    expect(borrowedCharacterReferences(character, 'wedding').map((e) => e.id)).toEqual([
      'portrait',
      'wedding_sheet',
      'outfit',
    ]);
  });

  it('falls back to the default sheet for the face when there is no portrait', () => {
    const character = {
      looks: [look('default', true, [sheet]), look('wedding', false, [outfit])],
    } as Character;
    expect(borrowedCharacterReferences(character, 'wedding').map((e) => e.id)).toEqual([
      'sheet',
      'outfit',
    ]);
  });
});

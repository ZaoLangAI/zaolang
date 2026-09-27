import { describe, expect, it } from 'vitest';

import type { ScriptDocument, ScriptScene } from './api';
import {
  boundVideoCount,
  dialogueLineKey,
  existingLibraryMatches,
  hasLinkedReference,
  libraryCharacterByName,
  linkedCharacterCount,
  linkedSceneCount,
  pendingCharacters,
  pendingDialogueLines,
  pendingScenes,
  pendingVideos,
  unreferencedVideoKeys,
} from './batch-plan';
import type { BreakpointVideoBinding } from './script-breakpoint';

const scene = (heading: string, overrides: Partial<ScriptScene> = {}): ScriptScene => ({
  heading,
  ref_id: null,
  blocks: [
    { type: 'action', character: null, text: '走动' },
    { type: 'breakpoint', character: null, text: 'cut' },
  ],
  ...overrides,
});

const document = (overrides: Partial<ScriptDocument> = {}): ScriptDocument => ({
  title: '',
  logline: '',
  characters: [
    { name: '苏晴', traits: '短发', character_ref_id: null },
    { name: '周野', traits: '西装', character_ref_id: 'sk_zhou' },
  ],
  scenes: [scene('公寓客厅'), scene('走廊')],
  ...overrides,
});

describe('pendingCharacters / pendingScenes', () => {
  it('skips already-linked characters and in-flight names', () => {
    const doc = document();
    expect(pendingCharacters(doc).map((item) => item.name)).toEqual(['苏晴']);
    expect(pendingCharacters(doc, new Set(['苏晴']))).toEqual([]);
    expect(linkedCharacterCount(doc)).toBe(1);
  });

  it('skips already-linked scenes and in-flight headings', () => {
    const doc = document({
      scenes: [scene('公寓客厅', { ref_id: 'sk_apt' }), scene('走廊')],
    });
    expect(pendingScenes(doc).map((item) => item.heading)).toEqual(['走廊']);
    expect(pendingScenes(doc, new Set(['走廊']))).toEqual([]);
    expect(linkedSceneCount(doc)).toBe(1);
  });
});

describe('existingLibraryMatches', () => {
  it('matches unlinked script names against the library after trim', () => {
    const doc = document({
      characters: [
        { name: '林彻', traits: '', character_ref_id: null },
        { name: '母亲模仿者', traits: '', character_ref_id: null },
        { name: '周野', traits: '', character_ref_id: 'sk_zhou' },
      ],
    });
    const matches = existingLibraryMatches(doc, [
      { id: 'sk_lin', name: ' 林彻 ', created_at: '2026-01-01T00:00:00Z' },
    ]);
    expect(matches).toEqual([{ name: '林彻', refId: 'sk_lin' }]);
  });

  it('does not re-match an already-linked or in-flight character', () => {
    const doc = document({
      characters: [
        { name: '林彻', traits: '', character_ref_id: 'sk_old' },
        { name: '母亲模仿者', traits: '', character_ref_id: null },
      ],
    });
    expect(
      existingLibraryMatches(
        doc,
        [
          { id: 'sk_lin', name: '林彻' },
          { id: 'sk_mom', name: '母亲模仿者' },
        ],
        new Set(['母亲模仿者']),
      ),
    ).toEqual([]);
  });

  it('keeps the newest library card when two share a name', () => {
    const byName = libraryCharacterByName([
      { id: 'sk_old', name: '林彻', created_at: '2026-01-01T00:00:00Z' },
      { id: 'sk_new', name: '林彻', created_at: '2026-02-01T00:00:00Z' },
    ]);
    expect(byName.get('林彻')?.id).toBe('sk_new');
  });
});

describe('hasLinkedReference', () => {
  it('is false until any character or scene is linked', () => {
    expect(
      hasLinkedReference(
        document({
          characters: [{ name: '苏晴', traits: '', character_ref_id: null }],
          scenes: [scene('公寓客厅')],
        }),
      ),
    ).toBe(false);
  });

  it('is true when a character or a scene is linked', () => {
    expect(hasLinkedReference(document())).toBe(true);
    expect(
      hasLinkedReference(
        document({
          characters: [{ name: '苏晴', traits: '', character_ref_id: null }],
          scenes: [scene('公寓客厅', { ref_id: 'sk_apt' })],
        }),
      ),
    ).toBe(true);
  });
});

describe('pendingVideos', () => {
  const bound = (assetId: string | null = 'ast_1'): BreakpointVideoBinding => ({
    draftId: 'drf_1',
    latestJobId: 'job_1',
    outputAssetId: assetId,
  });

  it('skips bound keys, in-flight keys, and segments with no refs', () => {
    const doc = document({
      characters: [{ name: '苏晴', traits: '', character_ref_id: null }],
      scenes: [scene('公寓客厅', { ref_id: 'sk_apt' }), scene('走廊')],
    });
    const pending = pendingVideos(doc, { '公寓客厅#0': bound() });
    expect(pending.map((item) => item.key)).toEqual([]);
    expect(boundVideoCount(doc, { '公寓客厅#0': bound() })).toBe(1);
    expect(unreferencedVideoKeys(doc, { '公寓客厅#0': bound() })).toEqual(['走廊#0']);
  });

  it('includes an unbound segment that has a scene or character ref', () => {
    const doc = document({
      characters: [{ name: '苏晴', traits: '', character_ref_id: 'sk_su' }],
      scenes: [
        {
          heading: '公寓客厅',
          ref_id: 'sk_apt',
          blocks: [
            { type: 'dialogue', character: '苏晴', text: '谁？' },
            { type: 'breakpoint', character: null, text: 'cut' },
          ],
        },
      ],
    });
    const pending = pendingVideos(doc, {});
    expect(pending).toHaveLength(1);
    expect(pending[0]?.key).toBe('公寓客厅#0');
    expect(pending[0]?.sceneId).toBe('sk_apt');
    expect(pending[0]?.characterIds).toEqual(['sk_su']);
    expect(pending[0]?.prompt).toContain('苏晴');
  });

  it('does not re-queue an in-flight unbound key', () => {
    const doc = document({
      scenes: [scene('公寓客厅', { ref_id: 'sk_apt' })],
    });
    expect(pendingVideos(doc, {}, new Set(['公寓客厅#0']))).toEqual([]);
  });
});

describe('pendingDialogueLines', () => {
  const dubDoc = (overrides: Partial<ScriptDocument> = {}): ScriptDocument =>
    document({
      scenes: [
        {
          heading: '公寓客厅',
          ref_id: null,
          blocks: [
            { type: 'action', character: null, text: '她走进房间' },
            { type: 'dialogue', character: '苏晴', text: '谁在那儿？' },
            { type: 'dialogue', character: '周野', text: '是我。' },
            { type: 'breakpoint', character: null, text: 'cut' },
          ],
        },
        scene('走廊'),
      ],
      ...overrides,
    });

  it('collects every non-empty dialogue block, keyed by heading + block index', () => {
    const pending = pendingDialogueLines(dubDoc());
    expect(pending.map((item) => item.key)).toEqual(['公寓客厅#L1', '公寓客厅#L2']);
    expect(pending[0]).toEqual({
      key: '公寓客厅#L1',
      heading: '公寓客厅',
      blockIndex: 1,
      character: '苏晴',
      text: '谁在那儿？',
    });
    expect(pending[1]?.character).toBe('周野');
  });

  it('does not require any character or scene ref, unlike pendingVideos', () => {
    // No `character_ref_id`/`ref_id` anywhere in `dubDoc()` — dubbing only
    // needs a line's own text, so it still shows up.
    expect(pendingDialogueLines(dubDoc())).toHaveLength(2);
  });

  it('skips blank dialogue and non-dialogue block types', () => {
    const doc = dubDoc({
      scenes: [
        {
          heading: '公寓客厅',
          ref_id: null,
          blocks: [
            { type: 'dialogue', character: '苏晴', text: '   ' },
            { type: 'camera', character: null, text: '推近' },
          ],
        },
      ],
    });
    expect(pendingDialogueLines(doc)).toEqual([]);
  });

  it('skips already-dubbed and in-flight keys', () => {
    const doc = dubDoc();
    expect(pendingDialogueLines(doc, new Set(['公寓客厅#L1']))).toEqual([
      expect.objectContaining({ key: '公寓客厅#L2' }),
    ]);
    expect(pendingDialogueLines(doc, new Set(), new Set(['公寓客厅#L2']))).toEqual([
      expect.objectContaining({ key: '公寓客厅#L1' }),
    ]);
  });

  it('never collides with a breakpointKey-shaped id', () => {
    // `{heading}#{ordinal}` (video) vs `{heading}#L{blockIndex}` (audio) —
    // deliberately different shapes so `indexBreakpointVideos` can never
    // mistake a dubbed line for a bound video, or vice versa.
    expect(dialogueLineKey('公寓客厅', 0)).toBe('公寓客厅#L0');
    expect(dialogueLineKey('公寓客厅', 0)).not.toBe('公寓客厅#0');
  });
});

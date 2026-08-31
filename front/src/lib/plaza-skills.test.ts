import { describe, expect, it } from 'vitest';

import type { CreationSkillSummary } from '@/lib/api/types';

import { overlayUnlockedSkills } from './plaza-skills';

function skill(overrides: Partial<CreationSkillSummary>): CreationSkillSummary {
  return {
    id: 'skl_a',
    title: '都市霓虹后巷',
    description: '',
    category: 'scene',
    author: { user_id: 'u_1', handle: 'studio', display_name: 'Studio' },
    visibility: 'public',
    status: 'published',
    usage_count: 0,
    access_credits: 0,
    viewer_unlocked: false,
    created_at: '2026-08-31T00:00:00Z',
    ...overrides,
  };
}

describe('overlayUnlockedSkills', () => {
  it('returns the incoming list when nothing has been unlocked this visit', () => {
    const scene = skill({ id: 'skl_scene', category: 'scene' });
    const list = [scene];
    expect(overlayUnlockedSkills(list, new Set())).toBe(list);
  });

  it('follows a new skills prop instead of keeping a previous batch', () => {
    const scene = skill({ id: 'skl_scene', title: '都市霓虹后巷', category: 'scene' });
    const lens = skill({ id: 'skl_lens', title: '过肩镜头·正面对峙', category: 'lens' });
    const first = overlayUnlockedSkills([scene], new Set());
    expect(first.map((item) => item.id)).toEqual(['skl_scene']);
    const next = overlayUnlockedSkills([lens], new Set());
    expect(next.map((item) => item.id)).toEqual(['skl_lens']);
  });

  it('keeps a local unlock overlay when the same skill is still in the list', () => {
    const paid = skill({
      id: 'skl_paid',
      access_credits: 12,
      viewer_unlocked: false,
    });
    const overlaid = overlayUnlockedSkills([paid], new Set(['skl_paid']));
    expect(overlaid[0]?.viewer_unlocked).toBe(true);
    expect(overlaid[0]?.access_credits).toBe(12);
  });
});

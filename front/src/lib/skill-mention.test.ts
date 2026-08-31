import { describe, expect, it } from 'vitest';

import type { CreationSkillSummary } from '@/lib/api/types';

import {
  detectMentionTrigger,
  filterMentionSkills,
  isSkillApplicableToOperation,
  isSkillMentionable,
  isSkillUsableForMention,
  stripMentionToken,
} from './skill-mention';

function skill(overrides: Partial<CreationSkillSummary>): CreationSkillSummary {
  return {
    id: 'skl_a',
    title: '环绕运镜·角色亮相',
    description: '',
    category: 'lens',
    author: { user_id: 'u_1', handle: 'studio', display_name: 'Studio' },
    visibility: 'public',
    status: 'published',
    usage_count: 0,
    access_credits: 0,
    viewer_unlocked: true,
    created_at: '2026-08-31T00:00:00Z',
    ...overrides,
  };
}

describe('detectMentionTrigger', () => {
  it('opens after a leading @', () => {
    expect(detectMentionTrigger('@环', 2)).toEqual({ start: 0, query: '环' });
  });

  it('opens after whitespace, not inside an email', () => {
    expect(detectMentionTrigger('hi @lens', 8)).toEqual({ start: 3, query: 'lens' });
    expect(detectMentionTrigger('a@b', 3)).toBeNull();
  });

  it('closes once the caret leaves the token', () => {
    expect(detectMentionTrigger('@lens more', 10)).toBeNull();
  });
});

describe('skill mention filters', () => {
  it('treats empty applicable_operations as any operation', () => {
    const anyOp = skill({ applicable_operations: [] });
    expect(isSkillApplicableToOperation(anyOp, 'text_to_image')).toBe(true);
    expect(isSkillApplicableToOperation(anyOp, 'text_to_video')).toBe(true);
  });

  it('excludes a video-only catalogue skill from image creation', () => {
    const videoOnly = skill({
      applicable_operations: ['text_to_video', 'image_to_video', 'video_to_video'],
    });
    expect(isSkillApplicableToOperation(videoOnly, 'text_to_image')).toBe(false);
    expect(isSkillMentionable(videoOnly, 'text_to_image')).toBe(false);
    expect(isSkillMentionable(videoOnly, 'text_to_video')).toBe(true);
  });

  it('excludes a locked paid skill from the @ list', () => {
    const locked = skill({ access_credits: 20, viewer_unlocked: false });
    expect(isSkillUsableForMention(locked)).toBe(false);
    expect(isSkillMentionable(locked, 'text_to_video')).toBe(false);
  });

  it('includes a purchased paid skill when it applies to the operation', () => {
    const bought = skill({
      access_credits: 20,
      viewer_unlocked: true,
      applicable_operations: ['text_to_image', 'image_to_image'],
    });
    expect(isSkillMentionable(bought, 'text_to_image')).toBe(true);
    expect(isSkillMentionable(bought, 'text_to_video')).toBe(false);
  });

  it('never mentions an image-asset skill via skill_ids', () => {
    const character = skill({ category: 'character', applicable_operations: [] });
    expect(isSkillMentionable(character, 'text_to_image')).toBe(false);
  });

  it('filters the open menu by title query', () => {
    const orbit = skill({ id: 'skl_1', title: '环绕运镜·角色亮相' });
    const crash = skill({ id: 'skl_2', title: '急速变焦·情绪冲击' });
    expect(filterMentionSkills([orbit, crash], '环绕').map((item) => item.id)).toEqual(['skl_1']);
  });
});

describe('stripMentionToken', () => {
  it('drops the @title token and its trailing space', () => {
    expect(stripMentionToken('用 @环绕运镜·角色亮相 开场', '环绕运镜·角色亮相')).toBe('用 开场');
  });
});

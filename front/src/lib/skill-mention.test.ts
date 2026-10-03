import { describe, expect, it } from 'vitest';

import type { CreationSkillSummary } from '@/lib/api/types';

import {
  creationStudioHref,
  detectMentionTrigger,
  filterMentionSkills,
  firstSkillReferenceAssetId,
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
    has_variables: false,
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

  it('excludes a user-authored character with empty operations from @', () => {
    const character = skill({ category: 'character', applicable_operations: [] });
    expect(isSkillMentionable(character, 'text_to_image')).toBe(false);
  });

  it('mentions a free image-asset recipe that declares text_to_image', () => {
    const recipe = skill({
      category: 'character',
      title: '三视图设定板',
      applicable_operations: ['text_to_image', 'image_to_image'],
    });
    expect(isSkillMentionable(recipe, 'text_to_image')).toBe(true);
    expect(isSkillMentionable(recipe, 'text_to_video')).toBe(false);
    expect(creationStudioHref(recipe)).toBe(
      '/create/new?mode=image_creation&skillId=skl_a&assetKind=character',
    );
  });

  it('sends an image-only template to the image studio', () => {
    const poster = skill({
      category: 'style',
      applicable_operations: ['text_to_image', 'image_to_image'],
    });
    expect(creationStudioHref(poster)).toBe('/create/new?mode=image_creation&skillId=skl_a');
  });

  it('carries the character asset kind into the video studio for a roster skill with no declared operations', () => {
    const character = skill({ category: 'character', applicable_operations: [] });
    expect(creationStudioHref(character)).toBe(
      '/create/new?mode=video_creation&skillId=skl_a&assetKind=character&videoAssetKind=character_action',
    );
  });

  it('uses the card anchor from the skill detail, else the cover', () => {
    expect(firstSkillReferenceAssetId('ast_cover', 'ast_anchor')).toBe('ast_anchor');
    expect(firstSkillReferenceAssetId('ast_cover')).toBe('ast_cover');
    expect(firstSkillReferenceAssetId(null, null)).toBeUndefined();
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

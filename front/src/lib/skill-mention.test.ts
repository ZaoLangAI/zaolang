import { describe, expect, it } from 'vitest';

import type { CreationSkillSummary } from '@/lib/api/types';

import {
  assetCreationHref,
  detectMentionTrigger,
  filterMentionSkills,
  firstSkillReferenceAssetId,
  isImageOnlyTemplate,
  isSkillApplicableToOperation,
  isSkillMentionable,
  isSkillUsableForMention,
  skillCardKind,
  stripMentionToken,
  videoCreationHref,
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
    // An asset card is never an image-only template, whatever it declares.
    expect(isImageOnlyTemplate(recipe)).toBe(false);
  });

  it('offers an image-only template to the three asset libraries as a style skill', () => {
    const poster = skill({
      category: 'style',
      applicable_operations: ['text_to_image', 'image_to_image'],
    });
    expect(isImageOnlyTemplate(poster)).toBe(true);
    expect(assetCreationHref('character', poster.id)).toBe('/create/characters?skillId=skl_a');
    expect(assetCreationHref('scene', poster.id)).toBe('/create/scenes?skillId=skl_a');
    expect(assetCreationHref('prop', poster.id)).toBe('/create/props?skillId=skl_a');
    expect(isImageOnlyTemplate(skill({ category: 'style', applicable_operations: [] }))).toBe(
      false,
    );
    expect(
      isImageOnlyTemplate(
        skill({ category: 'lens', applicable_operations: ['text_to_image', 'text_to_video'] }),
      ),
    ).toBe(false);
  });

  it('sends an asset card to video creation, preselected only when it is the viewer’s own', () => {
    const owner = { user_id: 'usr_me', display_name: '我', handle: 'me' };
    const character = skill({ category: 'character', applicable_operations: [], author: owner });
    expect(videoCreationHref(character, 'usr_me')).toBe(
      '/create/new?mode=video_creation&skillId=skl_a&videoAssetKind=character_action&referenceCharacterIds=skl_a',
    );
    expect(videoCreationHref(character, 'usr_other')).toBe(
      '/create/new?mode=video_creation&skillId=skl_a&videoAssetKind=character_action',
    );
    const scene = skill({ category: 'scene_asset', author: owner });
    expect(videoCreationHref(scene, 'usr_me')).toBe(
      '/create/new?mode=video_creation&skillId=skl_a&referenceSceneIds=skl_a',
    );
    const prop = skill({ category: 'prop_asset', author: owner });
    expect(videoCreationHref(prop, 'usr_me')).toBe(
      '/create/new?mode=video_creation&skillId=skl_a&referencePropIds=skl_a',
    );
    expect(skillCardKind(prop)).toBe('prop');
    const template = skill({ category: 'lens', applicable_operations: ['text_to_video'] });
    expect(videoCreationHref(template, 'usr_me')).toBe(
      '/create/new?mode=video_creation&skillId=skl_a',
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

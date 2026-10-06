import { describe, expect, it } from 'vitest';

import { parseStyleSkillId, withStyleSkill } from './style-skill';

describe('parseStyleSkillId', () => {
  it('keeps a well-formed skill id only', () => {
    expect(parseStyleSkillId('sk_01ABCdef')).toBe('sk_01ABCdef');
    expect(parseStyleSkillId('sk_../x')).toBeNull();
    expect(parseStyleSkillId('job_01')).toBeNull();
    expect(parseStyleSkillId(undefined)).toBeNull();
    expect(parseStyleSkillId(`sk_${'a'.repeat(40)}`)).toBeNull();
  });
});

describe('withStyleSkill', () => {
  it('appends the carried skill to a card link', () => {
    expect(withStyleSkill('/create/props/sk_p', 'sk_style')).toBe(
      '/create/props/sk_p?skillId=sk_style',
    );
    expect(withStyleSkill('/create/characters/sk_c?slot=portrait', 'sk_style')).toBe(
      '/create/characters/sk_c?slot=portrait&skillId=sk_style',
    );
  });

  it('leaves the link alone without one', () => {
    expect(withStyleSkill('/create/scenes/sk_s', null)).toBe('/create/scenes/sk_s');
  });
});

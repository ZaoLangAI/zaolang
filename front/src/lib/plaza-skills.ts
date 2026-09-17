import type { CreationSkillSummary } from '@/lib/api/types';

/**
 * The plaza grid is a client island that outlives a category-query
 * navigation, so the displayed list must be derived from the latest
 * `skills` prop rather than a `useState` snapshot. Unlock badges from this
 * visit are overlaid on top so a successful unlock still flips the card
 * without a refetch.
 */
export function overlayUnlockedSkills(
  skills: CreationSkillSummary[],
  unlockedIds: ReadonlySet<string>,
): CreationSkillSummary[] {
  if (unlockedIds.size === 0) return skills;
  return skills.map((skill) =>
    unlockedIds.has(skill.id) ? { ...skill, viewer_unlocked: true } : skill,
  );
}

'use client';

import { useLocale } from 'next-intl';
import { useMemo, useState } from 'react';

import { SkillCard } from '@/components/skills/skill-card';
import { SkillDetailDialog } from '@/components/skills/skill-detail-dialog';
import type { Locale } from '@/i18n/routing';
import type { CreationSkillSummary } from '@/lib/api/types';
import { overlayUnlockedSkills } from '@/lib/plaza-skills';

/**
 * The plaza's grid, split out from the (server) page component so clicking a
 * card can actually do something.
 *
 * Every card's click opens the same `SkillDetailDialog` regardless of
 * `CreationSkillCategory` — viewing is free for anyone, the backend already
 * empties `params` for a locked paid skill (`_detail()` in
 * `app/api/v1/skills.py`). The dialog owns every category-specific action
 * (unlock / apply-and-enter-studio / jump to the character or scene library /
 * manage a cover) behind its own buttons; this grid only tracks which skill
 * is currently open and overlays `viewer_unlocked` onto the incoming list
 * once the dialog reports a successful unlock, so a card's price badge flips
 * without a full page refetch.
 *
 * The displayed list is always derived from the latest `skills` prop — a
 * category Link re-fetches on the server but reuses this client island, so
 * copying the first batch into `useState` would keep showing the previous
 * category after the URL changes.
 */
export function SkillPlazaGrid({ skills }: { skills: CreationSkillSummary[] }) {
  const locale = useLocale() as Locale;

  const [unlockedIds, setUnlockedIds] = useState(() => new Set<string>());
  const [viewingId, setViewingId] = useState<string | null>(null);

  const items = useMemo(() => overlayUnlockedSkills(skills, unlockedIds), [skills, unlockedIds]);
  const viewingSkill = viewingId ? (items.find((item) => item.id === viewingId) ?? null) : null;

  const markUnlocked = (skillId: string) => {
    setUnlockedIds((current) => {
      const next = new Set(current);
      next.add(skillId);
      return next;
    });
  };

  return (
    <>
      <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {items.map((skill) => (
          <SkillCard
            key={skill.id}
            skill={skill}
            locale={locale}
            onClick={() => setViewingId(skill.id)}
          />
        ))}
      </ul>

      <SkillDetailDialog
        skill={viewingSkill}
        onClose={() => setViewingId(null)}
        onUnlocked={markUnlocked}
      />
    </>
  );
}

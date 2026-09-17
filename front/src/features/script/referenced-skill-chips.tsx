'use client';

import { useTranslations } from 'next-intl';

import { IconClose } from '@/components/ui/icons';
import type { CreationSkillSummary } from '@/lib/api/types';

/**
 * The small pill row above the composer's textarea, one per skill the
 * current draft references. This is the *visible* half of the reference —
 * the other half is the `@Title` text token sitting inline in the message
 * — so removing a chip here also has to strip that token from the text
 * (done by the caller, which owns the message string).
 */
export function ReferencedSkillChips({
  skills,
  onRemove,
}: {
  skills: CreationSkillSummary[];
  onRemove: (skillId: string) => void;
}) {
  const t = useTranslations('scriptStudio');

  if (skills.length === 0) return null;

  return (
    <ul className="flex flex-wrap gap-1.5 px-3 pt-2.5">
      {skills.map((skill) => (
        <li
          key={skill.id}
          className="flex items-center gap-1 rounded-full border border-primary/30 bg-primary/10 py-1 pl-2.5 pr-1 text-xs text-primary"
        >
          <span className="max-w-[9rem] truncate">{skill.title}</span>
          <button
            type="button"
            onClick={() => onRemove(skill.id)}
            aria-label={t('mentionRemove', { title: skill.title })}
            className="grid size-4 shrink-0 place-items-center rounded-full text-primary/70 transition-colors hover:bg-primary/20 hover:text-primary"
          >
            <IconClose className="size-3" />
          </button>
        </li>
      ))}
    </ul>
  );
}

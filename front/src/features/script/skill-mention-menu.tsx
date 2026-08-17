'use client';

import { useTranslations } from 'next-intl';

import { Poster } from '@/components/media/poster';
import { IconCheck } from '@/components/ui/icons';
import type { CreationSkillSummary } from '@/lib/api/types';
import { cn } from '@/lib/cn';

/**
 * The floating list an `@` trigger opens inside the composer's textarea.
 *
 * Purely presentational: it never takes DOM focus away from the textarea,
 * so all keyboard navigation (arrow keys, Enter/Tab, Escape) is driven by
 * `ScriptChatPanel`'s own `onKeyDown` against an `activeIndex` it owns —
 * this component only renders whichever index is currently active and
 * reports pointer interactions back up.
 */
export function SkillMentionMenu({
  skills,
  selectedIds,
  activeIndex,
  maxReached,
  style,
  onHoverIndex,
  onSelect,
}: {
  skills: CreationSkillSummary[];
  selectedIds: string[];
  activeIndex: number;
  maxReached: boolean;
  style: React.CSSProperties;
  onHoverIndex: (index: number) => void;
  onSelect: (skill: CreationSkillSummary) => void;
}) {
  const t = useTranslations('scriptStudio');

  return (
    <div
      role="listbox"
      aria-label={t('referenceSkill')}
      style={style}
      className="absolute z-30 max-h-64 w-64 overflow-y-auto rounded-[var(--radius-md)] border border-border bg-surface-raised p-1.5 shadow-raised"
    >
      <p className="px-2 pb-1.5 pt-0.5 text-[11px] font-semibold uppercase tracking-wider text-muted">
        {t('referenceSkill')}
      </p>
      {skills.length === 0 ? (
        <p className="px-2 py-2 text-xs text-muted">{t('mentionEmpty')}</p>
      ) : (
        skills.map((skill, index) => {
          const selected = selectedIds.includes(skill.id);
          const locked = skill.access_credits > 0 && !skill.viewer_unlocked;
          const disabled = !selected && maxReached;
          return (
            <button
              key={skill.id}
              type="button"
              role="option"
              aria-selected={index === activeIndex}
              disabled={disabled}
              onMouseEnter={() => onHoverIndex(index)}
              onClick={() => onSelect(skill)}
              className={cn(
                'flex w-full items-center gap-2 rounded-[var(--radius-sm)] px-2 py-1.5 text-left text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50',
                index === activeIndex
                  ? 'bg-primary/12 text-primary'
                  : 'text-text hover:bg-surface-soft',
              )}
            >
              <Poster
                src={skill.cover_url}
                alt={skill.title}
                aspect="square"
                mediaType={skill.cover_media_type}
                className="size-8 shrink-0"
              />
              <span className="min-w-0 flex-1 truncate">{skill.title}</span>
              {locked ? (
                <span className="shrink-0 text-[11px] text-muted">
                  {t('referenceSkillPrice', { credits: skill.access_credits })}
                </span>
              ) : null}
              {selected ? <IconCheck className="size-3.5 shrink-0 text-primary" /> : null}
            </button>
          );
        })
      )}
    </div>
  );
}

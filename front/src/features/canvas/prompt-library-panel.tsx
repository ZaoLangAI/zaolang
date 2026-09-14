'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useMemo, useState } from 'react';

import { SkillCard } from '@/components/skills/skill-card';
import { IconSearch } from '@/components/ui/icons';
import { Spinner } from '@/components/ui/spinner';
import type { CreationSkillSummary, Page } from '@/lib/api/types';
import { useResource } from '@/lib/use-resource';
import type { Locale } from '@/i18n/routing';
import { cn } from '@/lib/cn';

import { writeCanvasDrag } from './canvas-dnd';

/**
 * The prompt library, as a drawer on the canvas.
 *
 * Reads the same `GET /v1/skills/public?content_type=template` the plaza does
 * — scene / lens / style / format / other, the categories whose `params_json` is a flat
 * template rather than a character or scene asset. Picking one drops a `skill`
 * card bound to it; the card is the record, so nothing is "applied" here.
 *
 * **No unlock at placement.** A paid skill's card can be placed and wired
 * freely; `assert_unlocked_for_use` on the generation path is the gate that
 * actually matters, and charging to put a card down — one the user may drag
 * straight back off — would be charging for nothing. This is why the panel
 * does not go through `useAppliedSkills`: "applied" means folded into a form,
 * capped at five, and neither idea survives the trip to a canvas.
 */

const CATEGORIES = ['scene', 'lens', 'style', 'format', 'drama', 'other'] as const;

type Filter = 'all' | (typeof CATEGORIES)[number];

const CATEGORY_LABEL_KEY: Record<(typeof CATEGORIES)[number], string> = {
  scene: 'categoryScene',
  lens: 'categoryLens',
  style: 'categoryStyle',
  format: 'categoryFormat',
  drama: 'categoryDrama',
  other: 'categoryOther',
};

export function PromptLibraryPanel({
  onPick,
}: {
  /** Land a card for this skill at the viewport centre. Dragging bypasses
   * this and goes through the canvas' own drop handler instead. */
  onPick: (skill: CreationSkillSummary) => void;
}) {
  const t = useTranslations('canvas');
  const tSkill = useTranslations('skillLibrary');
  const locale = useLocale() as Locale;
  const [filter, setFilter] = useState<Filter>('all');
  const [query, setQuery] = useState('');

  const { status, data } = useResource<Page<CreationSkillSummary>>(
    '/v1/skills/public?content_type=template&limit=60',
  );

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (data?.items ?? []).filter((skill) => {
      if (filter !== 'all' && skill.category !== filter) return false;
      if (!needle) return true;
      return (
        skill.title.toLowerCase().includes(needle) ||
        (skill.description ?? '').toLowerCase().includes(needle)
      );
    });
  }, [data, filter, query]);

  return (
    <div className="flex max-h-[60vh] w-80 flex-col rounded-[var(--radius-md)] border border-border bg-surface shadow-sm">
      <div className="shrink-0 space-y-2 border-b border-border p-2">
        <p className="text-xs text-muted">{t('library.hint')}</p>
        <span className="relative block">
          <IconSearch className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted" />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t('library.search')}
            aria-label={t('library.search')}
            className="h-8 w-full rounded-[var(--radius-sm)] border border-border bg-surface-soft pl-8 pr-2.5 text-sm text-text placeholder:text-muted/70"
          />
        </span>
        <div className="flex flex-wrap gap-1">
          {(['all', ...CATEGORIES] as const).map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={filter === value}
              onClick={() => setFilter(value)}
              className={cn(
                'rounded-[var(--radius-sm)] px-2 py-0.5 text-[11px] transition-colors',
                filter === value
                  ? 'bg-primary/12 text-primary'
                  : 'text-muted hover:bg-surface-soft hover:text-text',
              )}
            >
              {value === 'all' ? t('library.all') : tSkill(CATEGORY_LABEL_KEY[value])}
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {status === 'failed' ? (
          <p className="text-xs text-danger">{t('library.failed')}</p>
        ) : !data ? (
          <Spinner />
        ) : visible.length === 0 ? (
          <p className="text-xs text-muted">{t('library.empty')}</p>
        ) : (
          <ul className="space-y-2">
            {visible.map((skill) => (
              <SkillCard
                key={skill.id}
                skill={skill}
                locale={locale}
                onClick={() => onPick(skill)}
                draggable
                onDragStart={(event) =>
                  writeCanvasDrag(event.dataTransfer, {
                    kind: 'skill',
                    label: skill.title,
                    binding: { kind: 'skill', skill_id: skill.id },
                  })
                }
              />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

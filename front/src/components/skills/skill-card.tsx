'use client';

import { useTranslations } from 'next-intl';

import { Poster } from '@/components/media/poster';
import { Badge } from '@/components/ui/primitives';
import type { CreationSkillSummary } from '@/lib/api/types';
import {
  CREATION_SKILL_STATUS_LABEL_KEY,
  CREATION_SKILL_STATUS_TONE,
} from '@/lib/creation-skill-status';
import { formatCount } from '@/lib/format';
import type { Locale } from '@/i18n/routing';

const CATEGORY_LABEL_KEY: Record<
  CreationSkillSummary['category'],
  | 'categoryScene'
  | 'categoryLens'
  | 'categoryStyle'
  | 'categoryCharacter'
  | 'categorySceneAsset'
  | 'categoryCoverAsset'
  | 'categoryOther'
> = {
  scene: 'categoryScene',
  lens: 'categoryLens',
  style: 'categoryStyle',
  character: 'categoryCharacter',
  scene_asset: 'categorySceneAsset',
  cover_asset: 'categoryCoverAsset',
  other: 'categoryOther',
};

/**
 * One skill's card, shared by the public plaza and the owner's library tab.
 *
 * `statusBadge` only renders for the owner's own view — a public visitor has
 * no use for "pending review", they only ever see skills that already made it
 * through moderation.
 */
export function SkillCard({
  skill,
  locale,
  showStatus,
  onClick,
  draggable,
  onDragStart,
}: {
  skill: CreationSkillSummary;
  locale: Locale;
  showStatus?: boolean;
  onClick?: () => void;
  /** Drag-to-place, used by the canvas' prompt library. Sits on the `<li>`
   * rather than on the inner button so the whole card is the drag handle —
   * and so a card with no `onClick` is still draggable. */
  draggable?: boolean;
  onDragStart?: (event: React.DragEvent<HTMLLIElement>) => void;
}) {
  const t = useTranslations('skillLibrary');

  const body = (
    <>
      <Poster
        src={skill.cover_url}
        alt={skill.title}
        aspect="video"
        className="rounded-none"
        mediaType={skill.cover_media_type}
      />
      <div className="p-4">
        <div className="flex items-center gap-1.5">
          <Badge tone="amber">{t(CATEGORY_LABEL_KEY[skill.category])}</Badge>
          {showStatus ? (
            <Badge tone={CREATION_SKILL_STATUS_TONE[skill.status]}>
              {t(CREATION_SKILL_STATUS_LABEL_KEY[skill.status])}
            </Badge>
          ) : null}
          {skill.access_credits > 0 ? (
            <Badge tone="primary">{t('priceCredits', { credits: skill.access_credits })}</Badge>
          ) : null}
        </div>
        <h3 className="mt-1.5 truncate text-sm font-semibold">{skill.title}</h3>
        {skill.description ? (
          <p className="mt-1.5 line-clamp-2 text-xs leading-relaxed text-muted">
            {skill.description}
          </p>
        ) : null}
        <div className="mt-3 flex items-center justify-between text-[11px] text-muted">
          <span>{t('byAuthor', { name: skill.author.display_name })}</span>
          <span className="tabular">{t('usageCount', { count: formatCount(skill.usage_count, locale) })}</span>
        </div>
      </div>
    </>
  );

  return (
    <li
      draggable={draggable}
      onDragStart={onDragStart}
      className="overflow-hidden rounded-[var(--radius-md)] border border-border bg-surface transition-colors hover:border-border-strong"
    >
      {onClick ? (
        <button type="button" onClick={onClick} className="block w-full text-left">
          {body}
        </button>
      ) : (
        body
      )}
    </li>
  );
}

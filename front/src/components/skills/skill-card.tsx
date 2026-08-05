'use client';

import { useTranslations } from 'next-intl';

import { Poster } from '@/components/media/poster';
import { Badge, type BadgeTone } from '@/components/ui/primitives';
import type { CreationSkillStatus, CreationSkillSummary } from '@/lib/api/types';
import { formatCount } from '@/lib/format';
import type { Locale } from '@/i18n/routing';

const CATEGORY_LABEL_KEY: Record<
  CreationSkillSummary['category'],
  'categoryScene' | 'categoryLens' | 'categoryStyle' | 'categoryOther'
> = {
  scene: 'categoryScene',
  lens: 'categoryLens',
  style: 'categoryStyle',
  other: 'categoryOther',
};

const STATUS_TONE: Record<CreationSkillStatus, BadgeTone> = {
  draft: 'neutral',
  pending_review: 'amber',
  published: 'success',
  rejected: 'danger',
};

const STATUS_LABEL_KEY: Record<
  CreationSkillStatus,
  'statusDraft' | 'statusPendingReview' | 'statusPublished' | 'statusRejected'
> = {
  draft: 'statusDraft',
  pending_review: 'statusPendingReview',
  published: 'statusPublished',
  rejected: 'statusRejected',
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
}: {
  skill: CreationSkillSummary;
  locale: Locale;
  showStatus?: boolean;
  onClick?: () => void;
}) {
  const t = useTranslations('skillLibrary');

  const body = (
    <>
      <Poster src={skill.cover_url} alt={skill.title} aspect="video" className="rounded-none" />
      <div className="p-4">
        <div className="flex items-center gap-1.5">
          <Badge tone="amber">{t(CATEGORY_LABEL_KEY[skill.category])}</Badge>
          {showStatus ? (
            <Badge tone={STATUS_TONE[skill.status]}>{t(STATUS_LABEL_KEY[skill.status])}</Badge>
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
    <li className="overflow-hidden rounded-[var(--radius-md)] border border-border bg-surface transition-colors hover:border-border-strong">
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

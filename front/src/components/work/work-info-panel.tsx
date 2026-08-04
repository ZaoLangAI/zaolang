'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { Avatar } from '@/components/work/avatar';
import { LineageStrip } from '@/components/work/lineage-strip';
import { ReusableParamsList } from '@/components/work/reusable-params';
import { Button } from '@/components/ui/button';
import {
  IconBookmark,
  IconBookmarkFilled,
  IconHeart,
  IconRemix,
  IconSparkle,
} from '@/components/ui/icons';
import { Badge } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { Link, useRouter } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import { api } from '@/lib/api/client';
import type { WorkDetail } from '@/lib/api/types';
import { formatCount, formatDate } from '@/lib/format';

/**
 * The right-hand panel from the design: provenance first, then the work.
 *
 * The order is deliberate and is a product requirement rather than a layout
 * preference — origin and licence come before the title, so a reader knows
 * whose work they are looking at before they know what it is called.
 */
export function WorkInfoPanel({
  work,
  compact = false,
  onBookmarkedChange,
}: {
  work: WorkDetail;
  /** Discover's hero panel trims the sections a detail page shows in full. */
  compact?: boolean;
  /**
   * The hero carousel unmounts cards once they rotate out of view, which
   * would otherwise reset `bookmarked` back to the server snapshot next time
   * this work rotates in. Letting the carousel mirror each toggle lets it
   * feed the current value back in through `work.viewer_bookmarked` on the
   * next mount.
   */
  onBookmarkedChange?: (bookmarked: boolean) => void;
}) {
  const t = useTranslations('work');
  const tPage = useTranslations('workPage');
  const locale = useLocale() as Locale;
  const router = useRouter();
  const { requireAuth } = useSession();
  const { notify } = useToast();

  const [liked, setLiked] = useState(work.viewer_liked);
  const [likes, setLikes] = useState(work.stats.like_count);
  const [bookmarked, setBookmarked] = useState(work.viewer_bookmarked);

  const toggleLike = () =>
    requireAuth({
      label: t('like'),
      run: async () => {
        const next = !liked;
        // Optimistic: the counter is cosmetic, and a like that waits for a
        // round trip feels broken.
        setLiked(next);
        setLikes((count) => count + (next ? 1 : -1));
        try {
          if (next) await api.post(`/v1/works/${work.id}/like`);
          else await api.delete(`/v1/works/${work.id}/like`);
        } catch {
          setLiked(!next);
          setLikes((count) => count + (next ? -1 : 1));
        }
      },
    });

  const toggleBookmark = () =>
    requireAuth({
      label: t('bookmark'),
      run: async () => {
        const next = !bookmarked;
        setBookmarked(next);
        onBookmarkedChange?.(next);
        try {
          if (next) await api.post(`/v1/works/${work.id}/bookmark`);
          else await api.delete(`/v1/works/${work.id}/bookmark`);
        } catch {
          setBookmarked(!next);
          onBookmarkedChange?.(!next);
        }
      },
    });

  const startRemix = () => {
    if (!work.can_remix) {
      notify(tPage('remixBlocked'), 'error');
      return;
    }
    requireAuth({ label: t('remixThis'), run: () => router.push(`/remix/${work.id}`) });
  };

  const isOriginal = work.ancestors === undefined || work.ancestors.length === 0;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-start justify-between gap-3">
        <Badge tone={isOriginal ? 'neutral' : 'amber'}>
          {isOriginal ? t('original') : t('remix')}
        </Badge>
        {work.license ? (
          <Badge tone="amber" icon={<IconSparkle className="size-3.5" />}>
            {work.license.attribution_text || work.license.license_type}
          </Badge>
        ) : null}
      </div>

      <div>
        <h1 className="text-2xl font-bold tracking-tight">{work.title}</h1>

        <Link
          href={`/profile/${work.author.handle}`}
          className="mt-3 flex items-center gap-2.5 text-sm"
        >
          <Avatar src={work.author.avatar_url} name={work.author.display_name} />
          <span>
            <span className="block font-medium">{work.author.display_name}</span>
            <span className="block text-xs text-muted">
              {work.published_at ? formatDate(work.published_at, locale) : t('viewOnly')}
            </span>
          </span>
        </Link>

        {work.description ? (
          <p className="mt-3 text-sm leading-relaxed text-muted">{work.description}</p>
        ) : null}

        <dl className="tabular mt-4 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-muted">
          <div className="flex items-center gap-1.5">
            <dt className="sr-only">{t('views')}</dt>
            <dd>{formatCount(work.stats.view_count, locale)}</dd>
            <span aria-hidden="true">{t('views')}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <dt className="sr-only">{t('likes')}</dt>
            <dd>{formatCount(likes, locale)}</dd>
            <span aria-hidden="true">{t('likes')}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <dt className="sr-only">{t('remixes')}</dt>
            <dd>{formatCount(work.stats.remix_count, locale)}</dd>
            <span aria-hidden="true">{t('remixes')}</span>
          </div>
        </dl>
      </div>

      <LineageStrip
        workId={work.id}
        ancestors={work.ancestors ?? []}
        author={work.author}
        descendantCount={work.descendant_count}
      />

      {/* Discover's hero panel is a teaser, not a remix workbench — the
          reusable-params breakdown belongs on the work page, where a reader
          has already committed to this piece. */}
      {work.reusable_params && !compact ? (
        <ReusableParamsList params={work.reusable_params} version={work.current_version} />
      ) : null}

      <div className="flex items-center gap-3">
        <Button
          size="lg"
          className="flex-1"
          icon={<IconRemix className="size-5" />}
          onClick={startRemix}
          disabled={!work.can_remix}
        >
          {work.can_remix ? t('remixThis') : t('notRemixable')}
        </Button>
        <Button
          size="lg"
          variant="secondary"
          icon={
            bookmarked ? (
              <IconBookmarkFilled className="size-5" />
            ) : (
              <IconBookmark className="size-5" />
            )
          }
          aria-pressed={bookmarked}
          onClick={toggleBookmark}
        >
          {bookmarked ? t('bookmarked') : t('bookmark')}
        </Button>
      </div>

      {compact ? null : (
        <div className="flex items-center gap-3 border-t border-border pt-4">
          <Button
            variant="ghost"
            size="sm"
            icon={<IconHeart className="size-4" />}
            aria-pressed={liked}
            onClick={toggleLike}
            className={liked ? 'text-primary' : undefined}
          >
            {liked ? t('liked') : t('like')}
          </Button>
          <p className="ml-auto flex items-center gap-1.5 text-xs text-muted">
            <IconSparkle className="size-3.5 text-amber" />
            {t('aiGenerated')}
          </p>
        </div>
      )}
    </div>
  );
}

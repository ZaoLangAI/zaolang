'use client';

import { useLocale, useTranslations } from 'next-intl';
import dynamic from 'next/dynamic';
import { useState } from 'react';

import { Poster } from '@/components/media/poster';
import { VideoPlayer } from '@/components/media/video-player';
import { Avatar } from '@/components/work/avatar';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { IconBranch, IconHeart, IconRemix, IconSparkle } from '@/components/ui/icons';
import { Badge, ErrorNotice, Skeleton } from '@/components/ui/primitives';
import { Link, useRouter } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import type { WorkDetail, WorkSummary } from '@/lib/api/types';
import { formatCount, formatDate } from '@/lib/format';
import { useResource } from '@/lib/use-resource';

const LineageDialog = dynamic(() =>
  import('@/components/lineage/lineage-dialog').then((module) => module.LineageDialog),
);

const PROMPT_MAX_LENGTH = 600;

/**
 * Preview of one inspiration tile without leaving the feed.
 *
 * The summary from the wall is enough to fill the header immediately, so the
 * dialog opens with the title and cover already painted and only the parts that
 * need the detail response (prompt, licence, description) arrive as skeletons.
 */
export function InspirationDialog({
  work,
  open,
  onClose,
}: {
  work: WorkSummary | null;
  open: boolean;
  onClose: () => void;
}) {
  const t = useTranslations('discover');
  const tWork = useTranslations('work');
  const tPage = useTranslations('workPage');
  const locale = useLocale() as Locale;
  const router = useRouter();

  const [lineageOpen, setLineageOpen] = useState(false);

  const detail = useResource<WorkDetail>(open && work ? `/v1/works/${work.id}` : null);
  const full = detail.data;

  if (!work) return null;

  const version = full?.current_version;
  const mediaType = full?.media_type ?? work.media_type;
  const mediaUrl = version?.media_url;
  const cover = version?.cover_url ?? full?.cover_url ?? work.cover_url;
  const prompt = full?.reusable_params?.prompt?.trim();
  const tags = work.tags ?? [];

  const createFromPrompt = (value: string) => {
    // Closing first keeps the dialog from lingering over the new route while
    // the navigation resolves.
    onClose();
    router.push({
      pathname: '/create/new',
      query: {
        mode: 'text_to_video',
        prompt: value.slice(0, PROMPT_MAX_LENGTH),
        ref: work.id,
      },
    });
  };

  return (
    <>
      <Dialog open={open} onClose={onClose} title={work.title} size="lg">
        <div className="flex flex-col gap-5">
          {mediaType === 'video' && mediaUrl ? (
            <VideoPlayer src={mediaUrl} poster={cover} title={work.title} />
          ) : (
            <Poster
              src={cover}
              alt={work.title}
              aspect="video"
              sizes="(max-width: 768px) 100vw, 720px"
              className="border border-border"
            />
          )}

          <div className="flex flex-wrap items-center justify-between gap-3">
            <Link
              href={`/profile/${work.author.handle}`}
              className="flex items-center gap-2.5 text-sm"
            >
              <Avatar src={work.author.avatar_url} name={work.author.display_name} />
              <span>
                <span className="block font-medium">{work.author.display_name}</span>
                <span className="block text-xs text-muted">
                  {work.published_at ? formatDate(work.published_at, locale) : tWork('viewOnly')}
                </span>
              </span>
            </Link>

            <dl className="tabular flex items-center gap-4 text-xs text-muted">
              <div className="flex items-center gap-1.5">
                <dt className="sr-only">{tWork('likes')}</dt>
                <IconHeart className="size-3.5" aria-hidden="true" />
                <dd>{formatCount(work.stats.like_count, locale)}</dd>
              </div>
              <div className="flex items-center gap-1.5">
                <dt className="sr-only">{tWork('remixes')}</dt>
                <IconRemix className="size-3.5" aria-hidden="true" />
                <dd>{formatCount(work.stats.remix_count, locale)}</dd>
              </div>
            </dl>
          </div>

          {tags.length > 0 ? (
            <ul className="flex flex-wrap gap-2">
              {tags.map((tag) => (
                <li key={tag}>
                  <Badge>{tag}</Badge>
                </li>
              ))}
            </ul>
          ) : null}

          {detail.status === 'failed' ? (
            <ErrorNotice title={tPage('notFound')} />
          ) : !full ? (
            <div className="flex flex-col gap-2" aria-busy="true">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-[70%]" />
              <Skeleton className="h-20 w-full" />
            </div>
          ) : (
            <>
              {full.description ? (
                <p className="text-sm leading-relaxed text-muted">{full.description}</p>
              ) : null}

              {full.license ? (
                <p className="flex items-center gap-1.5 text-xs text-muted">
                  <IconSparkle className="size-3.5 text-amber" />
                  {full.license.attribution_text || full.license.license_type}
                </p>
              ) : null}

              {prompt ? (
                <section className="rounded-[var(--radius-md)] border border-border bg-surface-soft p-4">
                  <h3 className="text-sm font-semibold">{t('promptTitle')}</h3>
                  <p className="mt-1 text-xs text-muted">{t('promptHint')}</p>
                  <button
                    type="button"
                    onClick={() => createFromPrompt(prompt)}
                    className="mt-3 w-full rounded-[var(--radius-sm)] border border-border bg-surface p-3 text-left text-sm leading-relaxed transition-colors hover:border-primary hover:text-primary focus-visible:outline-2"
                  >
                    {prompt}
                  </button>
                  <Button
                    className="mt-3"
                    size="sm"
                    icon={<IconSparkle className="size-4" />}
                    onClick={() => createFromPrompt(prompt)}
                  >
                    {t('createFromPrompt')}
                  </Button>
                </section>
              ) : (
                <p className="text-xs text-muted">{t('promptUnavailable')}</p>
              )}
            </>
          )}

          <div className="flex flex-wrap items-center gap-3 border-t border-border pt-4">
            <Button
              variant="secondary"
              size="sm"
              icon={<IconBranch className="size-4" />}
              onClick={() => setLineageOpen(true)}
            >
              {tWork('viewLineage')}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                onClose();
                router.push(`/work/${work.id}`);
              }}
            >
              {tPage('versionDetail')}
            </Button>
          </div>
        </div>
      </Dialog>

      {lineageOpen ? (
        <LineageDialog workId={work.id} open onClose={() => setLineageOpen(false)} />
      ) : null}
    </>
  );
}

'use client';

import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useRef, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { SignInPrompt } from '@/components/auth/sign-in-prompt';
import { Poster } from '@/components/media/poster';
import { Button } from '@/components/ui/button';
import {
  IconBranch,
  IconPencil,
  IconPlus,
  IconRefresh,
  IconTrash,
  IconTrashX,
} from '@/components/ui/icons';
import { Badge, EmptyState, SectionHeading } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import { getSeriesCanvas } from '@/features/canvas/api';
import * as editorApi from '@/features/editor/api';
import { Link, useRouter } from '@/i18n/navigation';
import { isApiError } from '@/lib/api/errors';

import { CollaboratorsPanel } from './collaborators-panel';
import { EpisodePreviewThumb } from './episode-preview-thumb';
import { episodeStatusTone, pascalCase } from './format';
import { PurgeSeriesDialog } from './purge-series-dialog';
import { SeriesAnalyticsOverview } from './series-analytics-overview';
import { SeriesFormDialog } from './series-form-dialog';
import { TrashSeriesDialog } from './trash-series-dialog';

/** `/create/short/series/{seriesId}`: the series' own episode roster. */
export function SeriesDetail({ seriesId }: { seriesId: string }) {
  const t = useTranslations('editor');
  const tCanvas = useTranslations('canvas');
  const { status } = useSession();
  const { notify } = useToast();
  const router = useRouter();

  const [series, setSeries] = useState<editorApi.DramaSeries | null>(null);
  const [episodes, setEpisodes] = useState<editorApi.DramaEpisode[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [trashOpen, setTrashOpen] = useState(false);
  const [purgeOpen, setPurgeOpen] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [openingCanvas, setOpeningCanvas] = useState(false);
  const previewFillAttempted = useRef(new Set<string>());

  const load = useCallback(() => {
    if (status !== 'authenticated') return;
    void Promise.all([editorApi.getDramaSeries(seriesId), editorApi.listEpisodes(seriesId)])
      .then(([seriesRow, episodeRows]) => {
        setSeries(seriesRow);
        setEpisodes(episodeRows);
        setLoaded(true);
      })
      .catch((error: unknown) => {
        if (isApiError(error) && error.isNotFound) setNotFound(true);
        setLoaded(true);
      });
  }, [seriesId, status]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const missing = episodes.filter(
      (item) =>
        !item.preview_url && item.has_preview_source && !previewFillAttempted.current.has(item.id),
    );
    if (missing.length === 0) return;
    for (const item of missing) previewFillAttempted.current.add(item.id);
    let cancelled = false;
    void (async () => {
      for (const item of missing) {
        if (cancelled) return;
        try {
          const updated = await editorApi.fillEpisodePreviewFromVideo(item.id);
          setEpisodes((current) =>
            current.map((episode) => (episode.id === updated.id ? updated : episode)),
          );
        } catch {
          // Empty poster stays; the thumb still offers a manual extract.
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [episodes]);

  const restore = () => {
    setRestoring(true);
    void editorApi
      .untrashDramaSeries(seriesId)
      .then((updated) => {
        setSeries(updated);
        notify(t('restoreSeriesDone'), 'success');
      })
      .catch((error: unknown) => {
        notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
      })
      .finally(() => setRestoring(false));
  };

  /** Resolve-or-create on the server, so the first visit needs no setup step
   * and every later one lands on the same canvas. */
  const openCanvas = () => {
    setOpeningCanvas(true);
    void getSeriesCanvas(seriesId)
      .then((canvas) => router.push(`/canvas/${canvas.id}`))
      .catch((error: unknown) => {
        notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
        setOpeningCanvas(false);
      });
  };

  if (status === 'anonymous') return <SignInPrompt description={t('signInHint')} />;
  if (status === 'loading' || !loaded) {
    return (
      <div className="grid min-h-[40vh] place-items-center">
        <Spinner label={t('dashboardLoading')} />
      </div>
    );
  }
  if (notFound || !series) {
    return (
      <EmptyState title={t('dashboardUnavailable')} description={t('dashboardUnavailableHint')} />
    );
  }

  const grouped = new Map<number, editorApi.DramaEpisode[]>();
  for (const episode of episodes) {
    const list = grouped.get(episode.season_number) ?? [];
    list.push(episode);
    grouped.set(episode.season_number, list);
  }
  const seasons = [...grouped.keys()].sort((a, b) => a - b);
  for (const seasonNumber of seasons) {
    grouped.get(seasonNumber)!.sort((a, b) => a.episode_number - b.episode_number);
  }

  const isTrashed = series.status === 'trashed';
  const isCollaborator = series.viewer_role === 'collaborator';

  return (
    <div className="flex flex-col gap-8">
      {isTrashed && !isCollaborator ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-md)] border border-danger/30 bg-danger/10 px-4 py-3">
          <p className="text-sm text-danger">{t('seriesTrashedBanner')}</p>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="secondary"
              icon={<IconRefresh className="size-3.5" />}
              loading={restoring}
              onClick={restore}
            >
              {t('restoreSeries')}
            </Button>
            <Button
              size="sm"
              variant="danger"
              icon={<IconTrashX className="size-3.5" />}
              disabled={episodes.length > 0}
              title={episodes.length > 0 ? t('purgeSeriesConfirmBodyBlocked') : undefined}
              onClick={() => setPurgeOpen(true)}
            >
              {t('purgeSeries')}
            </Button>
          </div>
        </div>
      ) : null}

      <div className="flex flex-wrap items-start gap-5">
        <Poster
          src={series.logo_url}
          alt={series.title}
          aspect="square"
          className="w-24 shrink-0 sm:w-28"
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-lg font-semibold">{series.title}</h2>
            <Button
              size="sm"
              variant="ghost"
              icon={<IconPencil className="size-3.5" />}
              onClick={() => setEditOpen(true)}
            >
              {t('seriesEditAction')}
            </Button>
            {/* Open to collaborators too: arranging the canvas is part of
                the same management grant as editing episodes and scripts. */}
            <Button
              size="sm"
              variant="ghost"
              icon={<IconBranch className="size-3.5" />}
              loading={openingCanvas}
              onClick={openCanvas}
            >
              {tCanvas('openCanvas')}
            </Button>
            {!isTrashed && !isCollaborator ? (
              <Button
                size="sm"
                variant="ghost"
                icon={<IconTrash className="size-3.5" />}
                onClick={() => setTrashOpen(true)}
              >
                {t('trashSeries')}
              </Button>
            ) : null}
          </div>
          {series.english_title ? (
            <p className="mt-0.5 text-sm text-muted">{series.english_title}</p>
          ) : null}
          {series.description ? (
            <p className="mt-1 text-sm text-muted">{series.description}</p>
          ) : null}
          <div className="mt-3 flex flex-wrap gap-1.5">
            {isCollaborator ? (
              <Badge tone="primary">
                {t('collaborationBadgeCreatedBy', { name: series.owner.display_name })}
              </Badge>
            ) : series.is_collaboration ? (
              <Badge tone="primary">{t('collaborationBadgeOwner')}</Badge>
            ) : null}
            {series.planned_episode_count ? (
              <Badge tone="neutral">
                {t('seriesPlannedEpisodeCountBadge', { count: series.planned_episode_count })}
              </Badge>
            ) : null}
            {series.genre_tags.map((genre) => (
              <Badge key={genre} tone="amber">
                {t(`genre${pascalCase(genre)}`)}
              </Badge>
            ))}
            {series.target_platforms.map((platform) => (
              <Badge key={platform} tone="neutral">
                {t(`channel${pascalCase(platform)}`)}
              </Badge>
            ))}
          </div>
        </div>

        {/* Fills the blank space next to the logo/title on wide screens
            instead of a full-width section further down the page; wraps
            below the title block on narrow ones via the row's flex-wrap. */}
        <div className="w-full sm:w-72 sm:shrink-0 md:w-80">
          <CollaboratorsPanel
            series={series}
            onChanged={() => {
              void editorApi.getDramaSeries(seriesId).then(setSeries);
            }}
          />
        </div>
      </div>

      {!isCollaborator ? <SeriesAnalyticsOverview seriesId={series.id} /> : null}

      <section>
        <SectionHeading
          title={t('episodesTitle')}
          action={
            <Link
              href={{ pathname: '/create/script', query: { seriesId: series.id } }}
              className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-border px-3 py-2 text-sm transition-colors hover:border-border-strong hover:bg-surface-soft"
            >
              <IconPlus className="size-4" />
              {t('addEpisodeAction')}
            </Link>
          }
        />
        {episodes.length === 0 ? (
          <EmptyState
            title={t('episodesEmpty')}
            description={t('episodesEmptyHint')}
            action={
              <Link
                href={{ pathname: '/create/script', query: { seriesId: series.id } }}
                className="rounded-[var(--radius-sm)] border border-border px-4 py-2 text-sm transition-colors hover:border-border-strong hover:bg-surface-soft"
              >
                {t('addEpisodeViaScript')}
              </Link>
            }
          />
        ) : (
          <div className="flex flex-col gap-6">
            {seasons.map((seasonNumber) => (
              <div key={seasonNumber}>
                <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">
                  {t('seasonLabel', { season: seasonNumber })}
                </p>
                <ul className="flex flex-col gap-2">
                  {grouped.get(seasonNumber)!.map((episode) => (
                    <li key={episode.id}>
                      <div className="flex items-center gap-3 rounded-[var(--radius-md)] border border-border bg-surface px-3 py-2 transition-colors hover:border-border-strong hover:bg-surface-soft sm:px-4 sm:py-3">
                        <EpisodePreviewThumb
                          episode={episode}
                          onUpdated={(updated) =>
                            setEpisodes((current) =>
                              current.map((item) => (item.id === updated.id ? updated : item)),
                            )
                          }
                        />
                        <Link
                          href={`/create/short/episodes/${episode.id}`}
                          className="flex min-w-0 flex-1 flex-wrap items-center gap-3 py-1"
                        >
                          <Badge tone="neutral">
                            {t(`episodeKind${pascalCase(episode.episode_kind)}`)}
                          </Badge>
                          <span className="min-w-0 flex-1 truncate text-sm font-medium">
                            {episode.episode_number}. {episode.title}
                          </span>
                          {!episode.has_script_turns ? (
                            <Badge tone="amber">{t('scriptPendingBadge')}</Badge>
                          ) : null}
                          <Badge tone={episodeStatusTone(episode.status)}>
                            {t(`status${pascalCase(episode.status)}`)}
                          </Badge>
                        </Link>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </section>

      <SeriesFormDialog
        open={editOpen}
        onClose={() => setEditOpen(false)}
        series={series}
        onSaved={(updated) => setSeries(updated)}
      />

      <TrashSeriesDialog
        seriesId={series.id}
        open={trashOpen}
        onClose={() => setTrashOpen(false)}
        onTrashed={() => {
          setTrashOpen(false);
          router.replace('/create/short');
        }}
      />

      <PurgeSeriesDialog
        seriesId={series.id}
        hasEpisodes={episodes.length > 0}
        open={purgeOpen}
        onClose={() => setPurgeOpen(false)}
        onPurged={() => {
          setPurgeOpen(false);
          router.replace('/create/short');
        }}
      />
    </div>
  );
}

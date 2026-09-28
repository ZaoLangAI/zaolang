'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { SignInPrompt } from '@/components/auth/sign-in-prompt';
import { Poster } from '@/components/media/poster';
import { Button, IconButton } from '@/components/ui/button';
import {
  IconArrowUp,
  IconBell,
  IconPlus,
  IconRefresh,
  IconSearch,
  IconTrash,
  IconTrashX,
} from '@/components/ui/icons';
import { Badge, EmptyState } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import * as editorApi from '@/features/editor/api';
import { Link } from '@/i18n/navigation';
import { isApiError } from '@/lib/api/errors';
import { cn } from '@/lib/cn';

import { CollaborationInvitesDialog } from './collaboration-invites-dialog';
import { pascalCase, SERIES_GENRES } from './format';
import { PurgeSeriesDialog } from './purge-series-dialog';
import { SeriesFormDialog } from './series-form-dialog';
import { TrashSeriesDialog } from './trash-series-dialog';

const SORT_FIELDS = ['updated_at', 'created_at'] as const;
type SortField = (typeof SORT_FIELDS)[number];
type SortDir = 'asc' | 'desc';

/**
 * The `/create/short` landing surface — the *only* place a new short drama
 * gets created. A searchable, sortable card library of every `kind=drama`
 * series the signed-in user owns; drilling into a card (episodes, content
 * links, canonical work, publishing) happens on
 * `/create/short/series/{id}`.
 */
export function DashboardShell() {
  const t = useTranslations('editor');
  const { status } = useSession();
  const { notify } = useToast();

  const [items, setItems] = useState<editorApi.DramaSeries[]>([]);
  const [unavailable, setUnavailable] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [view, setView] = useState<'active' | 'trash'>('active');
  const [trashingId, setTrashingId] = useState<string | null>(null);
  const [purgingId, setPurgingId] = useState<string | null>(null);
  const [restoringId, setRestoringId] = useState<string | null>(null);

  const [q, setQ] = useState('');
  const [genre, setGenre] = useState<string | null>(null);
  const [sort, setSort] = useState<SortField>('updated_at');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  const [invites, setInvites] = useState<editorApi.CollaborationInvite[]>([]);
  const [invitesOpen, setInvitesOpen] = useState(false);

  const reloadInvites = () => {
    if (status !== 'authenticated') return;
    void editorApi
      .listMyCollaborationInvites()
      .then(setInvites)
      .catch(() => undefined);
  };

  useEffect(() => {
    reloadInvites();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  const reload = () => {
    if (status !== 'authenticated') return;
    void editorApi
      .listDramaSeries({
        q: q.trim() || undefined,
        genre: genre ?? undefined,
        sort,
        sort_dir: sortDir,
        status: view === 'trash' ? 'trashed' : undefined,
      })
      .then((rows) => {
        setItems(rows);
        setLoaded(true);
      })
      .catch((error: unknown) => {
        if (isApiError(error) && error.isNotFound) setUnavailable(true);
        else notify(isApiError(error) ? error.message : t('dashboardUnavailable'), 'error');
        setLoaded(true);
      });
  };

  useEffect(() => {
    const handle = window.setTimeout(reload, 250);
    return () => window.clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [genre, q, sort, sortDir, status, view]);

  const toggleSort = (field: SortField) => {
    if (sort === field) {
      setSortDir((current) => (current === 'desc' ? 'asc' : 'desc'));
    } else {
      setSort(field);
      setSortDir('desc');
    }
  };

  const restore = (series: editorApi.DramaSeries) => {
    setRestoringId(series.id);
    void editorApi
      .untrashDramaSeries(series.id)
      .then(() => {
        setItems((current) => current.filter((item) => item.id !== series.id));
        notify(t('restoreSeriesDone'), 'success');
      })
      .catch((error: unknown) => {
        notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
      })
      .finally(() => setRestoringId(null));
  };

  if (status === 'anonymous') {
    return <SignInPrompt description={t('signInHint')} />;
  }
  if (status === 'loading' || !loaded) {
    return (
      <div className="grid min-h-[40vh] place-items-center">
        <Spinner label={t('dashboardLoading')} />
      </div>
    );
  }
  if (unavailable) {
    return (
      <EmptyState title={t('dashboardUnavailable')} description={t('dashboardUnavailableHint')} />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="relative">
          <IconSearch className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted" />
          <input
            type="search"
            value={q}
            onChange={(event) => setQ(event.target.value)}
            placeholder={t('seriesSearchPlaceholder')}
            className="h-9 w-64 rounded-[var(--radius-sm)] border border-border bg-surface-soft pl-8 pr-2.5 text-sm text-text placeholder:text-muted/70"
          />
        </span>

        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-3">
            {SORT_FIELDS.map((field) => (
              <button
                key={field}
                type="button"
                onClick={() => toggleSort(field)}
                className={cn(
                  'inline-flex items-center gap-1 text-sm transition-colors',
                  sort === field ? 'font-medium text-primary' : 'text-muted hover:text-text',
                )}
              >
                {t(field === 'updated_at' ? 'seriesSortUpdated' : 'seriesSortCreated')}
                <IconArrowUp
                  className={cn(
                    'size-3.5 transition-transform',
                    sort === field && sortDir === 'desc' ? 'rotate-180' : '',
                    sort === field ? 'opacity-100' : 'opacity-40',
                  )}
                />
              </button>
            ))}
          </div>
          <Button
            size="sm"
            variant="ghost"
            icon={<IconBell className="size-3.5" />}
            onClick={() => setInvitesOpen(true)}
          >
            {t('collaborationInvitesEntry')}
            {invites.length > 0 ? (
              <Badge tone="primary" className="ml-1">
                {invites.length}
              </Badge>
            ) : null}
          </Button>
          <Button
            size="sm"
            variant={view === 'trash' ? 'secondary' : 'ghost'}
            icon={<IconTrash className="size-3.5" />}
            onClick={() => setView((current) => (current === 'trash' ? 'active' : 'trash'))}
          >
            {view === 'trash' ? t('seriesTrashExit') : t('seriesTrashEnter')}
          </Button>
          {view === 'active' ? (
            <Button icon={<IconPlus className="size-4" />} onClick={() => setDialogOpen(true)}>
              {t('createSeries')}
            </Button>
          ) : null}
        </div>
      </div>

      {view === 'active' ? (
        <nav
          aria-label={t('seriesGenreTags')}
          className="no-scrollbar flex gap-2 overflow-x-auto pb-1"
        >
          <button
            type="button"
            onClick={() => setGenre(null)}
            className={cn(
              'shrink-0 rounded-full border px-3.5 py-1.5 text-xs transition-colors',
              genre === null
                ? 'border-primary bg-primary/12 text-primary'
                : 'border-border text-muted hover:border-border-strong hover:text-text',
            )}
          >
            {t('seriesGenreAll')}
          </button>
          {SERIES_GENRES.map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setGenre(value)}
              className={cn(
                'shrink-0 rounded-full border px-3.5 py-1.5 text-xs transition-colors',
                genre === value
                  ? 'border-primary bg-primary/12 text-primary'
                  : 'border-border text-muted hover:border-border-strong hover:text-text',
              )}
            >
              {t(`genre${pascalCase(value)}`)}
            </button>
          ))}
        </nav>
      ) : null}

      {items.length === 0 ? (
        <EmptyState
          title={view === 'trash' ? t('emptyTrash') : t('emptySeries')}
          description={view === 'trash' ? t('emptyTrashHint') : t('emptySeriesHint')}
          action={
            view === 'active' ? (
              <Button icon={<IconPlus className="size-4" />} onClick={() => setDialogOpen(true)}>
                {t('createSeries')}
              </Button>
            ) : undefined
          }
        />
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((series) => (
            <li
              key={series.id}
              className="flex flex-col overflow-hidden rounded-[var(--radius-md)] border border-border bg-surface transition-shadow hover:shadow-raised"
            >
              <Link
                href={`/create/short/series/${series.id}`}
                className="relative flex flex-1 flex-col"
              >
                <Poster
                  src={series.logo_url}
                  alt={series.title}
                  aspect="square"
                  className="w-full"
                />
                {view === 'trash' ? (
                  <span className="absolute right-2 top-2 flex gap-1.5">
                    <IconButton
                      label={t('restoreSeries')}
                      variant="secondary"
                      size="sm"
                      className="border-border bg-surface/90"
                      disabled={restoringId === series.id}
                      onClick={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        restore(series);
                      }}
                    >
                      <IconRefresh className="size-4" />
                    </IconButton>
                    <span aria-hidden className="my-1 w-px self-stretch bg-border" />
                    <IconButton
                      label={t('purgeSeries')}
                      variant="danger"
                      size="sm"
                      onClick={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        setPurgingId(series.id);
                      }}
                    >
                      <IconTrashX className="size-4" />
                    </IconButton>
                  </span>
                ) : series.viewer_role === 'owner' ? (
                  <IconButton
                    label={t('trashSeries')}
                    variant="secondary"
                    size="sm"
                    className="absolute right-2 top-2 border-border bg-surface/90"
                    onClick={(event) => {
                      event.preventDefault();
                      event.stopPropagation();
                      setTrashingId(series.id);
                    }}
                  >
                    <IconTrash className="size-4" />
                  </IconButton>
                ) : null}
                <div className="flex flex-1 flex-col gap-2 p-4">
                  <h3 className="truncate text-sm font-semibold">{series.title}</h3>
                  {series.viewer_role === 'collaborator' ? (
                    <p className="truncate text-xs text-muted">
                      {t('collaborationBadgeCreatedBy', { name: series.owner.display_name })}
                    </p>
                  ) : series.english_title ? (
                    <p className="truncate text-xs text-muted">{series.english_title}</p>
                  ) : null}
                  <div className="mt-auto flex flex-wrap gap-1.5 pt-2">
                    {series.viewer_role === 'collaborator' ? (
                      <Badge tone="primary">{t('collaborationBadge')}</Badge>
                    ) : series.is_collaboration ? (
                      <Badge tone="primary">{t('collaborationBadgeOwner')}</Badge>
                    ) : null}
                    <Badge tone="neutral">
                      {t('seriesScriptCount', { count: series.script_count })}
                    </Badge>
                    <Badge tone="neutral">
                      {t('seriesVideoCount', { count: series.video_count })}
                    </Badge>
                    <Badge tone="success">
                      {t('seriesPublishedCount', { count: series.published_count })}
                    </Badge>
                  </div>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}

      {trashingId ? (
        <TrashSeriesDialog
          seriesId={trashingId}
          open
          onClose={() => setTrashingId(null)}
          onTrashed={() => {
            setItems((current) => current.filter((item) => item.id !== trashingId));
            setTrashingId(null);
          }}
        />
      ) : null}

      {purgingId ? (
        <PurgeSeriesDialog
          seriesId={purgingId}
          hasEpisodes={(items.find((item) => item.id === purgingId)?.episode_count ?? 0) > 0}
          open
          onClose={() => setPurgingId(null)}
          onPurged={() => {
            setItems((current) => current.filter((item) => item.id !== purgingId));
            setPurgingId(null);
          }}
        />
      ) : null}

      <SeriesFormDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        series={null}
        onSaved={(series) => {
          setItems((current) => [series, ...current]);
          notify(t('seriesCreated'), 'success');
        }}
      />

      <CollaborationInvitesDialog
        invites={invites}
        open={invitesOpen}
        onClose={() => setInvitesOpen(false)}
        onResolved={(invite) => {
          setInvites((current) => current.filter((item) => item.id !== invite.id));
          reload();
        }}
      />
    </div>
  );
}

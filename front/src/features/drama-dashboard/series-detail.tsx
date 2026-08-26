'use client';

import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { SignInPrompt } from '@/components/auth/sign-in-prompt';
import { Button } from '@/components/ui/button';
import { Select, TextArea, TextInput } from '@/components/ui/field';
import { Badge, EmptyState, SectionHeading } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import * as editorApi from '@/features/editor/api';
import { Link } from '@/i18n/navigation';
import { isApiError } from '@/lib/api/errors';

import { episodeStatusTone, pascalCase } from './format';

const EPISODE_KINDS = ['main', 'trailer', 'teaser', 'bts', 'recap', 'other'] as const;

/** `/create/short/series/{seriesId}`: the series' own episode roster. */
export function SeriesDetail({ seriesId }: { seriesId: string }) {
  const t = useTranslations('editor');
  const { status } = useSession();
  const { notify } = useToast();

  const [series, setSeries] = useState<editorApi.DramaSeries | null>(null);
  const [episodes, setEpisodes] = useState<editorApi.DramaEpisode[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [notFound, setNotFound] = useState(false);

  const [title, setTitle] = useState('');
  const [season, setSeason] = useState('1');
  const [episodeNumber, setEpisodeNumber] = useState('');
  const [kind, setKind] = useState<string>('main');
  const [synopsis, setSynopsis] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (status !== 'authenticated') return;
    void Promise.all([editorApi.getDramaSeries(seriesId), editorApi.listEpisodes(seriesId)])
      .then(([seriesRow, episodeRows]) => {
        setSeries(seriesRow);
        setEpisodes(episodeRows);
        setLoaded(true);
      })
      .catch((error: unknown) => {
        if (isApiError(error) && error.isNotFound) setNotFound(true);
        else notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
        setLoaded(true);
      });
  }, [notify, seriesId, status, t]);

  const submitEpisode = useCallback(
    (event: React.FormEvent) => {
      event.preventDefault();
      const trimmedTitle = title.trim();
      if (!trimmedTitle) return;
      setBusy(true);
      void editorApi
        .createEpisode(seriesId, {
          title: trimmedTitle,
          season_number: season.trim() ? Number(season) : undefined,
          episode_number: episodeNumber.trim() ? Number(episodeNumber) : undefined,
          episode_kind: kind,
          synopsis: synopsis.trim() || undefined,
        })
        .then((episode) => {
          setEpisodes((current) => [...current, episode]);
          setTitle('');
          setEpisodeNumber('');
          setSynopsis('');
          notify(t('episodeCreated'), 'success');
        })
        .catch((error: unknown) => {
          notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
        })
        .finally(() => setBusy(false));
    },
    [episodeNumber, kind, notify, season, seriesId, synopsis, t, title],
  );

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

  const trimmedTitle = title.trim();

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h2 className="text-lg font-semibold">{series.title}</h2>
        {series.description ? (
          <p className="mt-1 text-sm text-muted">{series.description}</p>
        ) : null}
      </div>

      <section>
        <SectionHeading title={t('addEpisodeTitle')} />
        <form className="grid gap-4 sm:grid-cols-2" onSubmit={submitEpisode}>
          <TextInput
            label={t('episodeTitleFieldLabel')}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            required
            disabled={busy}
          />
          <Select
            label={t('episodeKindFieldLabel')}
            value={kind}
            onChange={(event) => setKind(event.target.value)}
            options={EPISODE_KINDS.map((value) => ({
              value,
              label: t(`episodeKind${pascalCase(value)}`),
            }))}
            disabled={busy}
          />
          <TextInput
            label={t('episodeSeasonFieldLabel')}
            type="number"
            min={1}
            value={season}
            onChange={(event) => setSeason(event.target.value)}
            disabled={busy}
          />
          <TextInput
            label={t('episodeNumberFieldLabel')}
            type="number"
            min={1}
            value={episodeNumber}
            onChange={(event) => setEpisodeNumber(event.target.value)}
            disabled={busy}
          />
          <div className="sm:col-span-2">
            <TextArea
              label={t('episodeSynopsisFieldLabel')}
              value={synopsis}
              onChange={(event) => setSynopsis(event.target.value)}
              disabled={busy}
            />
          </div>
          <div className="sm:col-span-2">
            <Button type="submit" loading={busy} disabled={!trimmedTitle}>
              {t('addEpisodeSubmit')}
            </Button>
          </div>
        </form>
      </section>

      <section>
        <SectionHeading title={t('episodesTitle')} />
        {episodes.length === 0 ? (
          <EmptyState title={t('episodesEmpty')} description={t('episodesEmptyHint')} />
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
                      <Link
                        href={`/create/short/episodes/${episode.id}`}
                        className="flex flex-wrap items-center gap-3 rounded-[var(--radius-md)] border border-border bg-surface px-4 py-3 transition-colors hover:border-border-strong hover:bg-surface-soft"
                      >
                        <Badge tone="neutral">
                          {t(`episodeKind${pascalCase(episode.episode_kind)}`)}
                        </Badge>
                        <span className="min-w-0 flex-1 truncate text-sm font-medium">
                          {episode.episode_number}. {episode.title}
                        </span>
                        <Badge tone={episodeStatusTone(episode.status)}>
                          {t(`status${pascalCase(episode.status)}`)}
                        </Badge>
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

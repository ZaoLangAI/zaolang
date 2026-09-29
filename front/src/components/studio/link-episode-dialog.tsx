'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Select } from '@/components/ui/field';
import { ErrorNotice } from '@/components/ui/primitives';
import * as editorApi from '@/features/editor/api';
import { isApiError } from '@/lib/api/errors';

/**
 * Picks an existing drama series + episode and attaches this draft as a
 * `candidate` content-link. Used by the video studio after a standalone
 * generation so the clip can land on a short-drama episode without going
 * through 文案创作 first.
 */
export function LinkEpisodeDialog({
  open,
  onClose,
  draftId,
  onLinked,
}: {
  open: boolean;
  onClose: () => void;
  draftId: string;
  onLinked: (episodeId: string) => void;
}) {
  const t = useTranslations('remixPage');
  const tActions = useTranslations('actions');
  const tStates = useTranslations('states');

  const [series, setSeries] = useState<editorApi.DramaSeries[]>([]);
  const [episodes, setEpisodes] = useState<editorApi.DramaEpisode[]>([]);
  const [seriesId, setSeriesId] = useState('');
  const [episodeId, setEpisodeId] = useState('');
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Resets adjusted during render rather than in the fetch effects (same
  // pattern as `command-palette.tsx`); the effects only do the fetching.
  const [wasOpen, setWasOpen] = useState(false);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setError(null);
      setLoading(true);
    }
  }
  const episodesSeriesId = open ? seriesId : '';
  const [lastEpisodesSeriesId, setLastEpisodesSeriesId] = useState('');
  if (episodesSeriesId !== lastEpisodesSeriesId) {
    setLastEpisodesSeriesId(episodesSeriesId);
    setEpisodeId('');
    if (!episodesSeriesId) setEpisodes([]);
  }

  useEffect(() => {
    if (!open) return;
    void editorApi
      .listDramaSeries()
      .then((rows) => {
        setSeries(rows);
        if (rows.length === 1) setSeriesId(rows[0]?.id ?? '');
      })
      .catch((caught) => {
        setError(isApiError(caught) ? caught.message : tStates('errorHint'));
      })
      .finally(() => setLoading(false));
  }, [open, tStates]);

  useEffect(() => {
    if (!episodesSeriesId) return;
    void editorApi
      .listEpisodes(episodesSeriesId)
      .then((rows) => {
        setEpisodes(rows);
        if (rows.length === 1) setEpisodeId(rows[0]?.id ?? '');
      })
      .catch((caught) => {
        setError(isApiError(caught) ? caught.message : tStates('errorHint'));
      });
  }, [episodesSeriesId, tStates]);

  const submit = async () => {
    if (!episodeId) return;
    setSubmitting(true);
    setError(null);
    try {
      await editorApi.createContentLink(episodeId, {
        content_type: 'draft',
        content_ref_id: draftId,
        role: 'candidate',
      });
      onLinked(episodeId);
      onClose();
    } catch (caught) {
      setError(isApiError(caught) ? caught.message : tStates('errorHint'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={t('linkEpisode')}
      description={t('linkEpisodeHint')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={submitting}>
            {tActions('cancel')}
          </Button>
          <Button onClick={() => void submit()} loading={submitting} disabled={!episodeId}>
            {t('linkEpisodeSubmit')}
          </Button>
        </>
      }
    >
      {error ? <ErrorNotice title={error} /> : null}
      {loading ? (
        <p className="text-sm text-muted">{tStates('loading')}</p>
      ) : series.length === 0 ? (
        <p className="text-sm text-muted">{t('linkEpisodeEmptySeries')}</p>
      ) : (
        <div className="flex flex-col gap-3">
          <Select
            label={t('linkEpisodeSeries')}
            value={seriesId}
            onChange={(event) => setSeriesId(event.target.value)}
            options={[
              { value: '', label: t('linkEpisodeSeriesPlaceholder') },
              ...series.map((item) => ({ value: item.id, label: item.title })),
            ]}
          />
          <Select
            label={t('linkEpisodeEpisode')}
            value={episodeId}
            onChange={(event) => setEpisodeId(event.target.value)}
            disabled={!seriesId}
            options={[
              {
                value: '',
                label: seriesId ? t('linkEpisodeEpisodePlaceholder') : t('linkEpisodePickSeriesFirst'),
              },
              ...episodes.map((item) => ({
                value: item.id,
                label: t('linkEpisodeOption', { number: item.episode_number, title: item.title }),
              })),
            ]}
          />
          {seriesId && episodes.length === 0 ? (
            <p className="text-xs text-muted">{t('linkEpisodeEmptyEpisodes')}</p>
          ) : null}
        </div>
      )}
    </Dialog>
  );
}

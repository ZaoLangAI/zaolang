'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Select } from '@/components/ui/field';
import { Spinner } from '@/components/ui/spinner';
import * as editorApi from '@/features/editor/api';

/**
 * Chooses the episode a canvas generation should belong to.
 *
 * This is the "send to short drama" step for a free canvas. It runs *before*
 * generating rather than after, because `EpisodeContentLink` can only point
 * at a draft / work / editor export — a note or a prompt card has nothing to
 * link yet. Picking here puts `linkEpisodeId` on the generation request, so
 * the draft is attached the moment it exists and the canvas picks it up as a
 * clip node on its next load.
 */
export function SendToSeriesDialog({
  open,
  onClose,
  onConfirm,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: (episodeId: string | null) => void;
}) {
  const t = useTranslations('canvas');
  const [series, setSeries] = useState<editorApi.DramaSeries[] | null>(null);
  const [seriesId, setSeriesId] = useState('');
  const [episodes, setEpisodes] = useState<editorApi.DramaEpisode[]>([]);
  const [episodeId, setEpisodeId] = useState('');

  useEffect(() => {
    if (!open) return undefined;
    let cancelled = false;
    void editorApi
      .listDramaSeries()
      .then((rows) => {
        if (!cancelled) setSeries(rows);
      })
      .catch(() => {
        if (!cancelled) setSeries([]);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  useEffect(() => {
    // No synchronous reset for the empty case: the episode picker is only
    // rendered while a series is chosen, and `onConfirm` sends `null` unless
    // both ids are set, so a stale value here is never read.
    if (!seriesId) return undefined;
    let cancelled = false;
    void editorApi
      .listEpisodes(seriesId)
      .then((rows) => {
        if (cancelled) return;
        setEpisodes(rows);
        setEpisodeId(rows[0]?.id ?? '');
      })
      .catch(() => {
        if (!cancelled) setEpisodes([]);
      });
    return () => {
      cancelled = true;
    };
  }, [seriesId]);

  return (
    <Dialog open={open} onClose={onClose} title={t('sendToSeriesTitle')}>
      <div className="space-y-4">
        <p className="text-xs text-muted">{t('sendToSeriesHint')}</p>
        {series === null ? (
          <Spinner label={t('sendToSeriesLoading')} />
        ) : (
          <>
            <Select
              label={t('sendToSeriesSeries')}
              value={seriesId}
              onChange={(event) => setSeriesId(event.target.value)}
              options={[
                { value: '', label: t('sendToSeriesNone') },
                ...series.map((row) => ({ value: row.id, label: row.title })),
              ]}
            />
            {seriesId ? (
              <Select
                label={t('sendToSeriesEpisode')}
                value={episodeId}
                onChange={(event) => setEpisodeId(event.target.value)}
                options={episodes.map((episode) => ({
                  value: episode.id,
                  label: `S${episode.season_number}E${episode.episode_number} · ${episode.title}`,
                }))}
              />
            ) : null}
          </>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t('cancel')}
          </Button>
          <Button
            onClick={() => onConfirm(seriesId && episodeId ? episodeId : null)}
            disabled={series === null || (seriesId !== '' && episodeId === '')}
          >
            {t('sendToSeriesConfirm')}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

'use client';

import { useTranslations } from 'next-intl';
import { useRef, useState } from 'react';

import { Poster } from '@/components/media/poster';
import { Button } from '@/components/ui/button';
import { IconImage, IconUpload, IconVideo } from '@/components/ui/icons';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import * as editorApi from '@/features/editor/api';
import { isApiError } from '@/lib/api/errors';
import { cn } from '@/lib/cn';
import { uploadFile } from '@/lib/upload';

type Busy = 'upload' | 'extract' | null;

/**
 * Roster thumbnail for one `DramaEpisode`. Upload and "from video" sit
 * outside the episode-row `Link` so those clicks never navigate away.
 */
export function EpisodePreviewThumb({
  episode,
  onUpdated,
  layout = 'row',
}: {
  episode: editorApi.DramaEpisode;
  onUpdated: (episode: editorApi.DramaEpisode) => void;
  layout?: 'row' | 'stack';
}) {
  const t = useTranslations('editor');
  const { notify } = useToast();
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState<Busy>(null);

  const apply = async (next: Promise<editorApi.DramaEpisode>, doneKey: string) => {
    const updated = await next;
    onUpdated(updated);
    notify(t(doneKey), 'success');
  };

  const handleUpload = async (file: File) => {
    setBusy('upload');
    try {
      const asset = await uploadFile(file, 'episode_preview');
      await apply(
        editorApi.updateEpisode(episode.id, { preview_asset_id: asset.id }),
        'episodePreviewUploadDone',
      );
    } catch (error: unknown) {
      notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
    } finally {
      setBusy(null);
      if (inputRef.current) inputRef.current.value = '';
    }
  };

  const handleExtract = async () => {
    setBusy('extract');
    try {
      await apply(editorApi.fillEpisodePreviewFromVideo(episode.id), 'episodePreviewExtractDone');
    } catch (error: unknown) {
      notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
    } finally {
      setBusy(null);
    }
  };

  const poster = (
    <Poster
      src={episode.preview_url}
      alt={episode.preview_url ? episode.title : t('episodePreviewEmpty')}
      aspect="portrait"
      sizes="80px"
      className="rounded-[var(--radius-sm)]"
    />
  );

  const fileInput = (
    <input
      ref={inputRef}
      type="file"
      accept="image/png,image/jpeg,image/webp"
      className="sr-only"
      disabled={busy !== null}
      onChange={(event) => {
        const file = event.target.files?.[0];
        if (file) void handleUpload(file);
      }}
    />
  );

  if (layout === 'stack') {
    return (
      <div className="flex flex-col gap-2">
        <p className="text-sm font-medium text-text">{t('episodePreviewLabel')}</p>
        <div className="relative w-24 overflow-hidden rounded-[var(--radius-sm)] border border-border">
          {poster}
          {busy ? (
            <div className="absolute inset-0 grid place-items-center bg-surface/70">
              <Spinner
                label={busy === 'upload' ? t('episodePreviewUploading') : t('episodePreviewExtracting')}
              />
            </div>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="secondary"
            icon={<IconUpload className="size-3.5" />}
            disabled={busy !== null}
            loading={busy === 'upload'}
            onClick={() => inputRef.current?.click()}
          >
            {t('episodePreviewUpload')}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            icon={<IconVideo className="size-3.5" />}
            disabled={busy !== null || !episode.has_preview_source}
            loading={busy === 'extract'}
            title={
              episode.has_preview_source
                ? t('episodePreviewFromVideoHint')
                : t('episodePreviewEmpty')
            }
            onClick={() => void handleExtract()}
          >
            {t('episodePreviewFromVideo')}
          </Button>
        </div>
        {fileInput}
      </div>
    );
  }

  return (
    <div className="group/preview relative w-14 shrink-0 sm:w-16">
      <div
        className={cn(
          'overflow-hidden rounded-[var(--radius-sm)] border border-border bg-surface-soft',
          !episode.preview_url && 'grid place-items-center',
        )}
      >
        {episode.preview_url ? (
          poster
        ) : (
          <span className="grid aspect-[3/4] w-full place-items-center text-muted">
            <IconImage className="size-5" />
            <span className="sr-only">{t('episodePreviewEmpty')}</span>
          </span>
        )}
        {busy ? (
          <div className="absolute inset-0 grid place-items-center bg-surface/70">
            <Spinner
              label={busy === 'upload' ? t('episodePreviewUploading') : t('episodePreviewExtracting')}
            />
          </div>
        ) : null}
      </div>
      <div className="absolute inset-x-0 bottom-0 flex justify-center gap-0.5 bg-gradient-to-t from-surface/95 to-transparent px-0.5 pb-1 pt-4 opacity-0 transition-opacity group-hover/preview:opacity-100 group-focus-within/preview:opacity-100">
        <button
          type="button"
          className="rounded-[var(--radius-sm)] bg-surface/90 p-1 text-text hover:bg-surface-raised focus-visible:outline-2 disabled:opacity-50"
          disabled={busy !== null}
          aria-label={t('episodePreviewUploadHint')}
          title={t('episodePreviewUploadHint')}
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            inputRef.current?.click();
          }}
        >
          <IconUpload className="size-3.5" />
        </button>
        {episode.has_preview_source ? (
          <button
            type="button"
            className="rounded-[var(--radius-sm)] bg-surface/90 p-1 text-text hover:bg-surface-raised focus-visible:outline-2 disabled:opacity-50"
            disabled={busy !== null}
            aria-label={t('episodePreviewFromVideoHint')}
            title={t('episodePreviewFromVideoHint')}
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              void handleExtract();
            }}
          >
            <IconVideo className="size-3.5" />
          </button>
        ) : null}
      </div>
      {fileInput}
    </div>
  );
}

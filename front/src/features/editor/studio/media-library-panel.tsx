'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useRef, useState } from 'react';

import { Button, IconButton } from '@/components/ui/button';
import { TextInput } from '@/components/ui/field';
import { IconGrid, IconMessage, IconUpload, IconVideo, IconWave } from '@/components/ui/icons';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import { isApiError } from '@/lib/api/errors';
import type { Asset } from '@/lib/upload';
import { uploadFile } from '@/lib/upload';

import * as editorApi from '../api';
import { TICKS_PER_SECOND, type EditCommand } from '../engine/ports';
import { useEditorUi } from '../store';
import { TranscriptReviewPanel } from '../transcript-review-panel';

type Tab = 'media' | 'captions';

const IMAGE_DEFAULT_DURATION_TICKS = 3 * TICKS_PER_SECOND;

/**
 * Adapted from OpenCut's `panels/assets/index.tsx` + `tabbar.tsx` — the
 * same tab-bar-plus-view-map shell, reduced to the two tabs this editor
 * actually has content for.
 */
export function MediaLibraryPanel({
  disabled,
  onApply,
  caption,
  onCaptionChange,
}: {
  disabled: boolean;
  onApply: (commands: EditCommand[]) => void;
  caption: string;
  onCaptionChange: (value: string) => void;
}) {
  const t = useTranslations('editor');
  const [tab, setTab] = useState<Tab>('media');

  return (
    <div className="flex h-full overflow-hidden">
      <div className="flex w-11 shrink-0 flex-col items-center gap-1 border-r border-border py-2">
        <IconButton
          label={t('mediaTabMedia')}
          variant={tab === 'media' ? 'secondary' : 'ghost'}
          onClick={() => setTab('media')}
        >
          <IconGrid className="size-4" />
        </IconButton>
        <IconButton
          label={t('mediaTabCaptions')}
          variant={tab === 'captions' ? 'secondary' : 'ghost'}
          onClick={() => setTab('captions')}
        >
          <IconMessage className="size-4" />
        </IconButton>
      </div>
      <div className="min-w-0 flex-1 overflow-y-auto p-3">
        {tab === 'media' ? (
          <MediaView disabled={disabled} onApply={onApply} />
        ) : (
          <CaptionsView
            disabled={disabled}
            onApply={onApply}
            caption={caption}
            onCaptionChange={onCaptionChange}
          />
        )}
      </div>
    </div>
  );
}

function MediaView({
  disabled,
  onApply,
}: {
  disabled: boolean;
  onApply: (commands: EditCommand[]) => void;
}) {
  const t = useTranslations('editor');
  const { notify } = useToast();
  const playheadTicks = useEditorUi((state) => state.playheadTicks);
  const [items, setItems] = useState<Asset[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [transcribingAssetId, setTranscribingAssetId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    editorApi
      .listMyMedia()
      .then((page) => {
        if (!cancelled) setItems(page.items);
      })
      .catch((error: unknown) => {
        if (!cancelled) setLoadError(isApiError(error) ? error.message : t('unavailable'));
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  const insert = (asset: Asset, elementType?: 'sticker') => {
    const trackId = asset.media_type === 'audio' ? 'trk_audio' : 'trk_video';
    const durationTicks =
      asset.duration_ms != null
        ? Math.max(1, Math.round((asset.duration_ms / 1000) * TICKS_PER_SECOND))
        : IMAGE_DEFAULT_DURATION_TICKS;
    onApply([
      {
        type: 'insert_clip',
        track_id: trackId,
        asset_id: asset.id,
        at_ticks: playheadTicks,
        duration_ticks: durationTicks,
        ...(elementType ? { element_type: elementType } : {}),
      },
    ]);
  };

  const upload = async (file: File) => {
    setUploading(true);
    try {
      const asset = await uploadFile(file, 'editor_source');
      setItems((current) => [asset, ...(current ?? [])]);
      notify(t('mediaUploadDone'), 'success');
    } catch (error) {
      notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div>
        <input
          ref={fileInputRef}
          type="file"
          accept="video/mp4,video/webm,audio/mpeg,audio/wav,audio/mp4,image/png,image/jpeg,image/webp"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = '';
            if (file) void upload(file);
          }}
        />
        <Button
          size="sm"
          variant="secondary"
          icon={<IconUpload className="size-4" />}
          loading={uploading}
          disabled={disabled}
          onClick={() => fileInputRef.current?.click()}
        >
          {t('mediaUpload')}
        </Button>
      </div>
      {loadError ? (
        <p className="text-xs text-danger">{loadError}</p>
      ) : items === null ? (
        <div className="grid place-items-center py-8">
          <Spinner label={t('loading')} />
        </div>
      ) : items.length === 0 ? (
        <p className="text-xs text-muted">{t('mediaLibraryEmpty')}</p>
      ) : (
        <ul className="grid grid-cols-2 gap-2">
          {items.map((asset) => (
            <li key={asset.id}>
              <MediaCard
                asset={asset}
                disabled={disabled}
                onInsert={() => insert(asset)}
                onInsertAsSticker={asset.media_type === 'image' ? () => insert(asset, 'sticker') : undefined}
                onTranscribe={
                  asset.media_type === 'video' || asset.media_type === 'audio'
                    ? () => setTranscribingAssetId(asset.id)
                    : undefined
                }
              />
            </li>
          ))}
        </ul>
      )}
      {transcribingAssetId ? (
        <TranscriptReviewPanel
          assetId={transcribingAssetId}
          disabled={disabled}
          onApply={onApply}
          onClose={() => setTranscribingAssetId(null)}
        />
      ) : null}
    </div>
  );
}

function MediaCard({
  asset,
  disabled,
  onInsert,
  onInsertAsSticker,
  onTranscribe,
}: {
  asset: Asset;
  disabled: boolean;
  onInsert: () => void;
  /** Only offered for images — a sticker is structurally a clip with `element_type: 'sticker'`, positioned/animated via the same transform keyframes any clip has (see `KeyframeControls`). */
  onInsertAsSticker?: () => void;
  /** Only offered for video/audio — opens `TranscriptReviewPanel` for this asset. */
  onTranscribe?: () => void;
}) {
  const t = useTranslations('editor');
  const durationLabel =
    asset.duration_ms != null ? `${(asset.duration_ms / 1000).toFixed(1)}s` : null;

  return (
    <div className="group flex w-full flex-col overflow-hidden rounded-[var(--radius-sm)] border border-border bg-surface-soft transition-colors hover:border-primary">
      <button
        type="button"
        disabled={disabled}
        onClick={onInsert}
        title={t('mediaInsert')}
        className="flex flex-col text-left disabled:cursor-not-allowed disabled:opacity-60"
      >
        <span className="relative flex aspect-video items-center justify-center bg-track">
          {asset.media_type === 'image' && asset.url ? (
            // eslint-disable-next-line @next/next/no-img-element -- short-lived signed URL, not a static asset Next can optimize
            <img
              src={asset.url}
              alt=""
              loading="lazy"
              decoding="async"
              className="size-full object-cover"
            />
          ) : asset.media_type === 'video' && asset.url ? (
            <video src={asset.url} muted preload="metadata" className="size-full object-cover" />
          ) : (
            <IconWave className="size-6 text-muted" />
          )}
          {durationLabel ? (
            <span className="absolute bottom-1 right-1 rounded bg-black/70 px-1 text-[10px] text-white">
              {durationLabel}
            </span>
          ) : null}
        </span>
        <span className="flex items-center gap-1 px-2 py-1 text-[11px] text-muted">
          {asset.media_type === 'video' ? (
            <IconVideo className="size-3" />
          ) : asset.media_type === 'audio' ? (
            <IconWave className="size-3" />
          ) : null}
          {asset.ai_generated ? t('mediaSourceGenerated') : t('mediaSourceUploaded')}
        </span>
      </button>
      {onInsertAsSticker ? (
        <button
          type="button"
          disabled={disabled}
          onClick={onInsertAsSticker}
          className="border-t border-border px-2 py-1 text-[11px] text-muted hover:text-fg disabled:cursor-not-allowed disabled:opacity-60"
        >
          {t('mediaInsertAsSticker')}
        </button>
      ) : null}
      {onTranscribe ? (
        <button
          type="button"
          disabled={disabled}
          onClick={onTranscribe}
          className="border-t border-border px-2 py-1 text-[11px] text-muted hover:text-fg disabled:cursor-not-allowed disabled:opacity-60"
        >
          {t('mediaTranscribe')}
        </button>
      ) : null}
    </div>
  );
}

function CaptionsView({
  disabled,
  onApply,
  caption,
  onCaptionChange,
}: {
  disabled: boolean;
  onApply: (commands: EditCommand[]) => void;
  caption: string;
  onCaptionChange: (value: string) => void;
}) {
  const t = useTranslations('editor');
  const playheadTicks = useEditorUi((state) => state.playheadTicks);

  return (
    <div className="flex flex-col gap-2">
      <TextInput
        label={t('captionText')}
        value={caption}
        onChange={(event) => onCaptionChange(event.target.value)}
        disabled={disabled}
      />
      <Button
        size="sm"
        disabled={disabled || !caption.trim()}
        onClick={() => {
          onApply([
            {
              type: 'insert_caption',
              track_id: 'trk_caption',
              at_ticks: playheadTicks,
              duration_ticks: TICKS_PER_SECOND * 2,
              text: caption.trim(),
            },
          ]);
          onCaptionChange('');
        }}
      >
        {t('insertCaption')}
      </Button>
    </div>
  );
}

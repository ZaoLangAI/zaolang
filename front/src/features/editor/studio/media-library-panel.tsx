'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useMemo, useRef, useState } from 'react';

import { Button, IconButton } from '@/components/ui/button';
import { TextInput } from '@/components/ui/field';
import {
  IconGrid,
  IconList,
  IconMessage,
  IconPlus,
  IconSearch,
  IconUpload,
  IconVideo,
  IconWave,
} from '@/components/ui/icons';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import { isApiError } from '@/lib/api/errors';
import { cn } from '@/lib/cn';
import type { Asset } from '@/lib/upload';
import { uploadFile } from '@/lib/upload';

import * as editorApi from '../api';
import { TICKS_PER_SECOND, type EditCommand } from '../engine/ports';
import { resolvedAssetFrom, useEditorUi } from '../store';
import { defaultInsertDuration, hasFileDrag, writeAssetDrag } from '../timeline/dnd';
import { TranscriptReviewPanel } from '../transcript-review-panel';

type Tab = 'media' | 'captions';
type ViewMode = 'grid' | 'list';

const ACCEPT = 'video/mp4,video/webm,audio/mpeg,audio/wav,audio/mp4,image/png,image/jpeg,image/webp';

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
      <div className="min-w-0 flex-1 overflow-hidden">
        {tab === 'media' ? (
          <MediaView disabled={disabled} onApply={onApply} />
        ) : (
          <div className="h-full overflow-y-auto p-3">
            <CaptionsView
              disabled={disabled}
              onApply={onApply}
              caption={caption}
              onCaptionChange={onCaptionChange}
            />
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Adapted from OpenCut's `panels/assets/views/media.tsx` — whole-panel drop
 * zone with an overlay, search box, grid/list toggle, and cards that are
 * both draggable onto the timeline and clickable to insert at the playhead.
 */
function MediaView({
  disabled,
  onApply,
}: {
  disabled: boolean;
  onApply: (commands: EditCommand[]) => void;
}) {
  const t = useTranslations('editor');
  const { notify } = useToast();
  const rememberAsset = useEditorUi((state) => state.rememberAsset);
  const [items, setItems] = useState<Asset[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [query, setQuery] = useState('');
  const [view, setView] = useState<ViewMode>('grid');
  const [transcribingAssetId, setTranscribingAssetId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dragDepthRef = useRef(0);

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

  // Every asset the library has seen is a legal `insert_clip` target for the
  // optimistic engine, even before the server's `asset_meta` includes it.
  useEffect(() => {
    for (const asset of items ?? []) {
      const resolved = resolvedAssetFrom(asset);
      if (resolved) rememberAsset(resolved);
    }
  }, [items, rememberAsset]);

  const filtered = useMemo(() => {
    if (!items) return null;
    const needle = query.trim().toLowerCase();
    if (!needle) return items;
    return items.filter((asset) => {
      const haystack = [
        asset.id,
        asset.media_type,
        asset.mime_type,
        asset.ai_generated ? t('mediaSourceGenerated') : t('mediaSourceUploaded'),
      ]
        .join(' ')
        .toLowerCase();
      return haystack.includes(needle);
    });
  }, [items, query, t]);

  const insert = (asset: Asset, elementType?: 'sticker') => {
    const trackId = asset.media_type === 'audio' ? 'trk_audio' : 'trk_video';
    const durationTicks = defaultInsertDuration({
      media_type: asset.media_type,
      duration_ticks:
        asset.duration_ms && asset.duration_ms > 0
          ? Math.round((asset.duration_ms / 1000) * TICKS_PER_SECOND)
          : null,
    });
    onApply([
      {
        type: 'insert_clip',
        track_id: trackId,
        asset_id: asset.id,
        at_ticks: useEditorUi.getState().playheadTicks,
        duration_ticks: durationTicks,
        ...(elementType ? { element_type: elementType } : {}),
      },
    ]);
  };

  const upload = async (files: File[]) => {
    if (files.length === 0) return;
    setUploading(true);
    try {
      for (const file of files) {
        const asset = await uploadFile(file, 'editor_source');
        setItems((current) => [asset, ...(current ?? [])]);
      }
      notify(t('mediaUploadDone'), 'success');
    } catch (error) {
      notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div
      className="relative flex h-full flex-col"
      onDragEnter={(event) => {
        if (disabled || !hasFileDrag(event.dataTransfer)) return;
        event.preventDefault();
        dragDepthRef.current += 1;
        setDragOver(true);
      }}
      onDragOver={(event) => {
        if (disabled || !hasFileDrag(event.dataTransfer)) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = 'copy';
      }}
      onDragLeave={() => {
        dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
        if (dragDepthRef.current === 0) setDragOver(false);
      }}
      onDrop={(event) => {
        dragDepthRef.current = 0;
        setDragOver(false);
        if (disabled || !hasFileDrag(event.dataTransfer)) return;
        event.preventDefault();
        const files = Array.from(event.dataTransfer.files);
        if (files.length === 0) return;
        // Dropping on the library only uploads; dropping on the timeline
        // (see `Timeline`) also inserts. Mirrors OpenCut's split.
        void upload(files);
      }}
    >
      {dragOver ? (
        <div className="pointer-events-none absolute inset-2 z-10 grid place-items-center rounded-[var(--radius-sm)] border-2 border-dashed border-primary bg-surface/80 text-sm text-primary">
          {t('mediaDropToUpload')}
        </div>
      ) : null}
      <div className="flex shrink-0 items-center gap-2 border-b border-border p-2">
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={ACCEPT}
          className="hidden"
          onChange={(event) => {
            const files = Array.from(event.target.files ?? []);
            event.target.value = '';
            void upload(files);
          }}
        />
        <div className="relative min-w-0 flex-1">
          <IconSearch className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t('mediaSearchPlaceholder')}
            aria-label={t('mediaSearchPlaceholder')}
            className="h-8 w-full rounded-[var(--radius-sm)] border border-border bg-surface pl-7 pr-2 text-xs text-text outline-none placeholder:text-muted focus:border-primary"
          />
        </div>
        <IconButton
          label={view === 'grid' ? t('mediaViewList') : t('mediaViewGrid')}
          variant="ghost"
          onClick={() => setView((current) => (current === 'grid' ? 'list' : 'grid'))}
        >
          {view === 'grid' ? <IconList className="size-4" /> : <IconGrid className="size-4" />}
        </IconButton>
        <IconButton
          label={t('mediaUpload')}
          variant="secondary"
          disabled={disabled || uploading}
          onClick={() => fileInputRef.current?.click()}
        >
          {uploading ? <Spinner className="size-4" /> : <IconUpload className="size-4" />}
        </IconButton>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {loadError ? (
          <p className="text-xs text-danger">{loadError}</p>
        ) : filtered === null ? (
          <div className="grid place-items-center py-8">
            <Spinner label={t('loading')} />
          </div>
        ) : filtered.length === 0 ? (
          <p className="px-1 py-6 text-center text-xs text-muted">
            {query ? t('mediaSearchEmpty') : t('mediaLibraryEmpty')}
          </p>
        ) : (
          <ul className={cn('min-w-0 gap-2', view === 'grid' ? 'grid grid-cols-2' : 'flex flex-col')}>
            {filtered.map((asset) => (
              <li key={asset.id} className="min-w-0">
                <MediaCard
                  asset={asset}
                  view={view}
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
          <div className="mt-3">
            <TranscriptReviewPanel
              assetId={transcribingAssetId}
              disabled={disabled}
              onApply={onApply}
              onClose={() => setTranscribingAssetId(null)}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}

function MediaCard({
  asset,
  view,
  disabled,
  onInsert,
  onInsertAsSticker,
  onTranscribe,
}: {
  asset: Asset;
  view: ViewMode;
  disabled: boolean;
  onInsert: () => void;
  /** Only offered for images — a sticker is structurally a clip with `element_type: 'sticker'`, positioned/animated via the same transform keyframes any clip has (see `KeyframeControls`). */
  onInsertAsSticker?: () => void;
  /** Only offered for video/audio — opens `TranscriptReviewPanel` for this asset. */
  onTranscribe?: () => void;
}) {
  const t = useTranslations('editor');
  const durationLabel = asset.duration_ms != null ? `${(asset.duration_ms / 1000).toFixed(1)}s` : null;
  const kindIcon =
    asset.media_type === 'video' ? (
      <IconVideo className="size-3" />
    ) : asset.media_type === 'audio' ? (
      <IconWave className="size-3" />
    ) : null;

  const thumb = (
    <span
      className={cn(
        'relative flex items-center justify-center overflow-hidden bg-track',
        view === 'grid' ? 'aspect-video w-full' : 'aspect-video w-20 shrink-0 rounded-[var(--radius-sm)]',
      )}
    >
      {asset.media_type === 'image' && asset.url ? (
        // eslint-disable-next-line @next/next/no-img-element -- short-lived signed URL, not a static asset Next can optimize
        <img
          src={asset.url}
          alt=""
          loading="lazy"
          decoding="async"
          // Same asset URL is also loaded crossOrigin="anonymous" by the
          // preview/export compositor's MediaPool — keeping this consistent
          // avoids the browser caching a non-CORS response for a URL the
          // compositor later needs to read pixels from.
          crossOrigin="anonymous"
          className="size-full object-cover"
        />
      ) : asset.media_type === 'video' && asset.url ? (
        <video src={asset.url} muted preload="metadata" crossOrigin="anonymous" className="size-full object-cover" />
      ) : (
        <IconWave className="size-6 text-muted" />
      )}
      {durationLabel ? (
        <span className="absolute bottom-1 right-1 rounded bg-black/70 px-1 text-[10px] text-white">
          {durationLabel}
        </span>
      ) : null}
      {!disabled ? (
        <span
          aria-hidden
          className="absolute right-1 top-1 grid size-6 place-items-center rounded-full bg-black/70 text-white opacity-0 transition-opacity group-hover:opacity-100"
        >
          <IconPlus className="size-3.5" />
        </span>
      ) : null}
    </span>
  );

  return (
    <div
      draggable={!disabled}
      onDragStart={(event) => {
        if (disabled) {
          event.preventDefault();
          return;
        }
        writeAssetDrag(event.dataTransfer, asset);
      }}
      className={cn(
        'group flex w-full min-w-0 overflow-hidden rounded-[var(--radius-sm)] border border-border bg-surface-soft transition-colors hover:border-primary',
        view === 'grid' ? 'flex-col' : 'flex-row items-stretch',
        !disabled && 'cursor-grab active:cursor-grabbing',
      )}
    >
      <button
        type="button"
        disabled={disabled}
        onClick={onInsert}
        // `aria-label`, not `title`: the button also has visible text content
        // and most browsers' accessible-name computation prefers that text.
        aria-label={t('mediaInsert')}
        title={t('mediaInsertHint')}
        className={cn(
          'flex min-w-0 flex-1 text-left disabled:cursor-not-allowed disabled:opacity-60',
          view === 'grid' ? 'flex-col' : 'flex-row items-center gap-2 p-1.5',
        )}
      >
        {thumb}
        <span
          className={cn(
            'flex min-w-0 items-center gap-1 text-[11px] text-muted',
            view === 'grid' ? 'px-2 py-1' : 'flex-col items-start gap-0',
          )}
        >
          <span className="flex items-center gap-1">
            {kindIcon}
            {asset.ai_generated ? t('mediaSourceGenerated') : t('mediaSourceUploaded')}
          </span>
          {view === 'list' ? <span className="truncate font-mono text-[10px]">{asset.id}</span> : null}
        </span>
      </button>
      {view === 'grid' && onInsertAsSticker ? (
        <button
          type="button"
          disabled={disabled}
          onClick={onInsertAsSticker}
          className="border-t border-border px-2 py-1 text-[11px] text-muted hover:text-fg disabled:cursor-not-allowed disabled:opacity-60"
        >
          {t('mediaInsertAsSticker')}
        </button>
      ) : null}
      {view === 'grid' && onTranscribe ? (
        <button
          type="button"
          disabled={disabled}
          onClick={onTranscribe}
          className="border-t border-border px-2 py-1 text-[11px] text-muted hover:text-fg disabled:cursor-not-allowed disabled:opacity-60"
        >
          {t('mediaTranscribe')}
        </button>
      ) : null}
      {view === 'list' && (onInsertAsSticker || onTranscribe) ? (
        <div className="flex shrink-0 flex-col justify-center gap-1 border-l border-border px-1.5">
          {onInsertAsSticker ? (
            <button
              type="button"
              disabled={disabled}
              onClick={onInsertAsSticker}
              className="text-[10px] text-muted hover:text-fg disabled:opacity-60"
            >
              {t('mediaInsertAsSticker')}
            </button>
          ) : null}
          {onTranscribe ? (
            <button
              type="button"
              disabled={disabled}
              onClick={onTranscribe}
              className="text-[10px] text-muted hover:text-fg disabled:opacity-60"
            >
              {t('mediaTranscribe')}
            </button>
          ) : null}
        </div>
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

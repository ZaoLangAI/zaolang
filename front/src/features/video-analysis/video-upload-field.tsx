'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useRef, useState } from 'react';

import { IconClose, IconUpload } from '@/components/ui/icons';
import { Spinner } from '@/components/ui/spinner';
import type { Locale } from '@/i18n/routing';
import { formatBytes, formatDuration } from '@/lib/format';
import type { Asset } from '@/lib/upload';
import { uploadFile } from '@/lib/upload';

/** Mirrors `VIDEO_ANALYSIS_MAX_DURATION_MS` in `app.domain.media.service`. */
const MAX_DURATION_MS = 180_000;

/**
 * The one-video upload dropzone for the video-analysis submit form.
 *
 * Deliberately its own small component rather than a reuse of
 * `SourceMaterialRail` — that one manages a multi-item, image-or-video
 * "materials" rail tied to the remix studio's inherited-material concept,
 * whereas this tool only ever has exactly one reference (enforced
 * server-side by `validate_generation_references`), so a single dropzone
 * that swaps in place reads far more clearly than an N-item rail capped at 1.
 */
export function VideoUploadField({
  asset,
  onChange,
}: {
  asset: Asset | null;
  onChange: (asset: Asset | null) => void;
}) {
  const t = useTranslations('videoAnalysisPage');
  const locale = useLocale() as Locale;
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pick = async (file: File | undefined) => {
    if (!file) return;
    setError(null);

    if (!file.type.startsWith('video/')) {
      setError(t('videoOnlyError'));
      return;
    }

    setBusy(true);
    try {
      const uploaded = await uploadFile(file, 'video_analysis_source');
      if (uploaded.duration_ms != null && uploaded.duration_ms > MAX_DURATION_MS) {
        setError(t('durationExceededError'));
        return;
      }
      onChange(uploaded);
    } catch {
      setError(t('uploadFailed'));
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = '';
    }
  };

  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-sm font-medium text-text">{t('uploadLabel')}</label>

      {asset ? (
        <div className="relative overflow-hidden rounded-[var(--radius-md)] border border-border bg-surface-soft">
          <video src={asset.url ?? undefined} controls preload="metadata" className="max-h-72 w-full" />
          <div className="flex items-center justify-between gap-3 border-t border-border bg-surface px-3 py-2">
            <p className="truncate text-xs text-muted">
              {formatBytes(asset.size_bytes, locale)}
              {asset.duration_ms != null ? ` · ${formatDuration(asset.duration_ms / 1000)}` : ''}
            </p>
            <div className="flex shrink-0 items-center gap-2">
              <button
                type="button"
                onClick={() => inputRef.current?.click()}
                className="text-xs text-muted hover:text-text"
              >
                {t('uploadReplace')}
              </button>
              <button
                type="button"
                aria-label={t('uploadRemove')}
                onClick={() => onChange(null)}
                className="grid size-7 place-items-center rounded-full text-muted hover:text-danger"
              >
                <IconClose className="size-4" />
              </button>
            </div>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={busy}
          className="flex min-h-40 w-full flex-col items-center justify-center gap-2 rounded-[var(--radius-md)] border border-dashed border-border text-sm text-muted transition-colors hover:border-border-strong hover:text-text disabled:opacity-60"
        >
          {busy ? <Spinner label={t('uploading')} /> : <IconUpload className="size-6" />}
          {!busy ? t('uploadCta') : null}
        </button>
      )}

      <input
        ref={inputRef}
        type="file"
        accept="video/*"
        aria-label={t('uploadLabel')}
        className="sr-only"
        onChange={(event) => void pick(event.target.files?.[0])}
      />

      <p className="text-xs leading-relaxed text-muted">{t('uploadHint')}</p>
      {error ? (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}
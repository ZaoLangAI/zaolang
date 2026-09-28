'use client';

import { useTranslations } from 'next-intl';
import { useCallback, useState } from 'react';

import { DevicePreview } from '@/components/media/device-preview';
import { Poster } from '@/components/media/poster';
import { SourceMaterialRail } from '@/components/studio/source-material-rail';
import { Button } from '@/components/ui/button';
import { IconClock, IconGear, IconMic, IconSparkle } from '@/components/ui/icons';
import { Sheet } from '@/components/ui/sheet';
import { DEFAULT_DEVICE_ID } from '@/lib/devices';
import { refreshWorkMediaUrl } from '@/lib/refresh-media-src';
import { useMinWidth } from '@/lib/use-media-query';
import type { ReusableParams, WorkDetail } from '@/lib/api/types';
import type { Asset } from '@/lib/upload';

/** A licensed remix source, or a plain draft with nothing inherited. */
export interface StudioSource {
  work: WorkDetail;
  params: ReusableParams;
}

/**
 * The layout shared by `ImageGenerationStudio`, `VideoGenerationStudio` and
 * `AudioGenerationStudio` — what used to be the bottom half of the single
 * `GenerationStudio` component (source rail | preview | params aside, the
 * mobile bottom bar, and the params `Sheet`).
 *
 * Each of the three shells owns its own state and its own params panel
 * content; this component only owns the parts of the page that look
 * identical regardless of what is being generated: where the source
 * materials go, where the preview goes, and how the params panel gets from
 * "always visible aside" (desktop) to "opened from a sheet" (narrow).
 */
export function GenerationStudioShell({
  source,
  reference,
  uploads,
  onUploaded,
  onRemove,
  onSelectUpload,
  isAudio = false,
  isPortraitPreview = false,
  previewSlot,
  previewOverrideUrl,
  previewPlaceholder,
  hideDirectHint = false,
  promptSlot,
  canSubmit,
  submitting,
  submitLabel,
  onSubmit,
  price,
  estimate,
  error,
  children,
}: {
  source?: StudioSource;
  /** A work the idea came from, carried over from the discover feed — never a remix source. */
  reference?: WorkDetail;
  uploads: Asset[];
  onUploaded: (asset: Asset) => void;
  onRemove: (assetId: string) => void;
  /** Clicking an uploaded thumbnail in `SourceMaterialRail` — shows it
   * enlarged in the preview area via `previewOverrideUrl` below. Omitted by
   * video/audio, which don't wire this up. */
  onSelectUpload?: (asset: Asset) => void;
  /** Swaps the preview for a "no picture" hint instead of a poster/device frame. */
  isAudio?: boolean;
  /** Whether the chosen aspect ratio is vertical — decides `DevicePreview` vs a plain `Poster`. */
  isPortraitPreview?: boolean;
  /**
   * Replaces the default cover/poster preview block entirely — used by
   * `ImageGenerationStudio` once a generation exists, so its inline progress
   * and result (`InlineImageResult`) render where the placeholder cover used
   * to be, instead of navigating to `/jobs/[jobId]`. The attribution strip,
   * writing-tip box and submit chrome below are unaffected. `undefined`
   * (video/audio, and the image studio before its first submit) keeps the
   * original `isAudio`/`isPortraitPreview` preview untouched.
   */
  previewSlot?: React.ReactNode;
  /** A source-material thumbnail the user clicked, shown enlarged in place
   * of the default cover/placeholder — only consulted when `previewSlot` is
   * absent (i.e. before the first submit). */
  previewOverrideUrl?: string | null;
  /** Overrides the empty-preview placeholder text (`t('promptLabel')`'s
   * default) — `ImageGenerationStudio` passes a dedicated "图片预览区域"
   * string here instead of reusing the prompt field's own label. */
  previewPlaceholder?: string;
  /** Hides the "写得更像导演" writing-tip box below the preview — the image
   * studio alone opts into this. Has no effect once `promptSlot` is set (see
   * below), since that box would just duplicate what the slot already
   * shows. */
  hideDirectHint?: boolean;
  /**
   * Renders directly beneath the preview/attribution block, in the main
   * column rather than the params aside/`Sheet` — all three studios pass
   * their `PromptComposer` here so the prompt field stays visible next to
   * the preview on every breakpoint instead of only inside "调整参数".
   * Replaces the standalone `directHint` box entirely when set (video and
   * audio fold that same copy into the composer's own header instead of
   * stacking two boxes) — `hideDirectHint` above is then moot.
   */
  promptSlot?: React.ReactNode;
  canSubmit: boolean;
  submitting: boolean;
  /** Overrides the default `submitting ? t('submitting') : t('submit')`
   * label — video / clip pass a polish- or generate-in-flight string here. */
  submitLabel?: string;
  onSubmit: () => void;
  price: string;
  estimate: string;
  error: string | null;
  /** The params panel content, mounted in exactly one of the desktop aside and the mobile sheet. */
  children: React.ReactNode;
}) {
  const t = useTranslations('remixPage');
  const [paramsRequested, setParamsRequested] = useState(false);

  // The sheet is the narrow layout's third column. Derived rather than closed
  // in an effect: at `lg` those controls are on the page, so "open" is not a
  // state the wide layout can be in at all.
  const isDesktop = useMinWidth('lg');
  const paramsOpen = paramsRequested && !isDesktop;
  // The panel's open/closed state (e.g. the style gallery dialog's) lives in
  // the studio above, so mounting `children` in both places opens every
  // portalled dialog in it twice — once from the aside that is merely
  // `hidden` below `lg`. The sheet mounts its content only while it is open,
  // so the aside steps aside for exactly that long. Keyed on `paramsOpen`
  // rather than `isDesktop` so the server, which has no viewport, still
  // renders the panel in the aside.
  const panelInAside = !paramsOpen;

  const cover =
    previewOverrideUrl ?? source?.work.current_version?.cover_url ?? source?.work.cover_url;
  const previewTitle = source?.work.title ?? previewPlaceholder ?? t('promptLabel');
  const sourceMediaType = source?.work.media_type ?? source?.work.current_version?.media_type;
  const sourceVideoUrl = source?.work.current_version?.media_url;
  const playSourceVideo =
    sourceMediaType === 'video' && Boolean(sourceVideoUrl) && !previewOverrideUrl;
  const refreshSourceVideo = useCallback(
    () => (source ? refreshWorkMediaUrl(source.work.id) : Promise.resolve(null)),
    [source],
  );

  return (
    <div className="flex flex-col gap-5 lg:grid lg:grid-cols-[184px_minmax(0,1fr)_340px]">
      <div className="order-2 min-w-0 lg:order-none">
        <SourceMaterialRail
          source={source}
          reference={reference}
          uploads={uploads}
          onUploaded={onUploaded}
          onRemove={onRemove}
          onSelectUpload={onSelectUpload}
          hideUpload={isAudio}
        />
      </div>

      <div className="order-1 flex min-w-0 flex-col gap-4 lg:order-none">
        {previewSlot ? (
          previewSlot
        ) : isAudio ? (
          // No frame to preview here — audio has no picture, so the slot that
          // would show one becomes a plain hint instead of an empty poster.
          <div className="flex aspect-video flex-col items-center justify-center gap-2 rounded-[var(--radius-md)] border border-border bg-surface-soft text-muted">
            <IconMic className="size-8" />
            <p className="text-xs">{t('audioPreviewHint')}</p>
          </div>
        ) : playSourceVideo ? (
          <DevicePreview
            src={sourceVideoUrl}
            poster={cover}
            title={previewTitle}
            mediaType="video"
            defaultDeviceId={isPortraitPreview ? DEFAULT_DEVICE_ID : undefined}
            maxHeight={480}
            refreshSrc={refreshSourceVideo}
          />
        ) : isPortraitPreview ? (
          // A vertical framing is the one the author cannot judge from a
          // 16:9 box, so that is where the phone frame earns its place.
          <DevicePreview
            poster={cover}
            title={previewTitle}
            defaultDeviceId={DEFAULT_DEVICE_ID}
            maxHeight={480}
          />
        ) : (
          <Poster src={cover} alt={previewTitle} aspect="video" className="border border-border" />
        )}

        {source ? (
          <div className="flex flex-wrap items-center justify-between gap-3 text-xs">
            <span className="flex items-center gap-1.5 text-success">
              <IconSparkle className="size-4" />
              {t('keepAttribution')}
            </span>
            <span className="text-muted">
              {source.work.author.display_name}
              {source.work.license ? ` · ${source.work.license.attribution_text}` : ''}
            </span>
          </div>
        ) : null}

        {promptSlot ? (
          promptSlot
        ) : !hideDirectHint ? (
          <div className="flex gap-3 rounded-[var(--radius-md)] border border-border bg-surface-soft p-4">
            <IconSparkle className="size-5 shrink-0 text-amber" />
            <div>
              <p className="text-sm font-medium">{t('directHint')}</p>
              <p className="mt-1 text-xs leading-relaxed text-muted">{t('directHintBody')}</p>
            </div>
          </div>
        ) : null}
      </div>

      <aside
        aria-labelledby="generation-params-heading"
        className="order-3 hidden flex-col gap-4 rounded-[var(--radius-md)] border border-border bg-surface p-4 lg:flex"
      >
        <h2 id="generation-params-heading" className="text-sm font-semibold">
          {t('howToGenerate')}
        </h2>
        {panelInAside ? children : null}
        <Button
          size="lg"
          onClick={onSubmit}
          disabled={!canSubmit}
          loading={submitting}
          icon={<IconSparkle className="size-5" />}
        >
          {submitLabel ?? (submitting ? t('submitting') : t('submit'))}
        </Button>
      </aside>

      {/* Keeps the end of the page clear of the fixed bar below. */}
      <div aria-hidden="true" className="safe-mb order-4 h-24 lg:hidden" />

      <div className="safe-b fixed inset-x-0 bottom-0 z-30 border-t border-border bg-surface lg:hidden">
        <div className="mx-auto flex max-w-[1440px] flex-col gap-2 px-4 py-3">
          {error && !paramsOpen ? (
            <p role="alert" className="text-xs text-danger">
              {error}
            </p>
          ) : null}
          <div className="flex items-center justify-between gap-3 text-xs">
            <p className="tabular font-semibold text-amber">{price}</p>
            <p className="tabular flex items-center gap-1.5 text-muted">
              <IconClock className="size-3.5" />
              {estimate}
            </p>
          </div>
          {/* The submit button takes the rest of the row rather than sizing to
              its label: it is the only control here that spends credits, and
              the label is the longest string in three languages. */}
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              onClick={() => setParamsRequested(true)}
              icon={<IconGear className="size-4" />}
              className="shrink-0"
            >
              {t('adjustParams')}
            </Button>
            <Button
              onClick={onSubmit}
              disabled={!canSubmit}
              loading={submitting}
              icon={<IconSparkle className="size-4" />}
              className="min-w-0 flex-1"
            >
              {submitLabel ?? (submitting ? t('submitting') : t('submit'))}
            </Button>
          </div>
        </div>
      </div>

      <Sheet
        open={paramsOpen}
        onClose={() => setParamsRequested(false)}
        title={t('howToGenerate')}
        description={t('adjustParamsHint')}
        footer={
          <Button variant="secondary" fullWidth onClick={() => setParamsRequested(false)}>
            {t('paramsDone')}
          </Button>
        }
      >
        {children}
      </Sheet>
    </div>
  );
}

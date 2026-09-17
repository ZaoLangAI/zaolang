'use client';

import { useTranslations } from 'next-intl';
import { useRef, useState } from 'react';

import { DeviceFrame } from '@/components/media/device-frame';
import { useAvailableStage } from '@/components/media/use-available-stage';
import { VideoPlayer } from '@/components/media/video-player';
import {
  DropdownMenu,
  DropdownMenuFooter,
  DropdownMenuGroup,
  DropdownMenuRadioItem,
} from '@/components/ui/dropdown-menu';
import { IconCheck, IconVideo } from '@/components/ui/icons';
import { MediaLightbox } from '@/components/ui/media-lightbox';
import { cn } from '@/lib/cn';
import {
  DEVICES,
  deviceById,
  fitWithinReferenceCanvas,
  referenceStageFallbackStyle,
  type PlatformChrome,
} from '@/lib/devices';

/** Selection that shows the clip without a phone around it. */
export const NO_DEVICE = 'none';

/**
 * The media stage with an optional phone around it.
 *
 * Defaults to the file's own ratio. Landscape follows the parent column;
 * portrait stays phone-sized so a 9:16 clip cannot pin itself to the
 * viewport. The phone frame is opt-in — most stills and landscape clips
 * are not phone-sized. Short-form callers pass `DEFAULT_DEVICE_ID` when
 * the author is composing for a vertical screen.
 */
export function DevicePreview({
  src,
  poster,
  title,
  defaultDeviceId = NO_DEVICE,
  maxHeight,
  edgeToEdge = false,
  chrome,
  overlay,
  className,
  refreshSrc,
  mediaType = 'video',
}: {
  src?: string | null;
  poster?: string | null;
  title: string;
  /** `NO_DEVICE`, or an id from the device catalogue. */
  defaultDeviceId?: string;
  /** Caps the stage height (framed or not) below the viewport-remaining
   * default `useAvailableStage` would otherwise compute — set this when a
   * caller has its own content (e.g. action buttons) directly below the
   * stage that also needs to stay visible without excessive scrolling. */
  maxHeight?: number;
  /**
   * The stage runs to the viewport edges on a phone, so the control row has to
   * carry the gutter its parent gave up.
   */
  edgeToEdge?: boolean;
  /** Reserved screen shares; defaults to the catalogue's guidance. */
  chrome?: PlatformChrome;
  /**
   * Drawn on the screen above the clip, e.g. the caption a short-form author is
   * writing. Only rendered inside a phone: with no frame there is no platform
   * UI for it to collide with, which is the only reason to show it.
   */
  overlay?: React.ReactNode;
  className?: string;
  /** Forwarded to `VideoPlayer` so a signed URL can be re-minted in place. */
  refreshSrc?: () => Promise<string | null>;
  mediaType?: 'image' | 'video';
}) {
  const t = useTranslations('devicePreview');

  const [deviceId, setDeviceId] = useState(defaultDeviceId);
  const [showSafeArea, setShowSafeArea] = useState(true);
  const [showPlatformChrome, setShowPlatformChrome] = useState(false);

  const stageRef = useRef<HTMLDivElement>(null);
  const avail = useAvailableStage(stageRef, maxHeight);

  const framed = deviceId !== NO_DEVICE;
  const device = deviceById(deviceId);
  const bodyWidth = device.width + device.bezel * 2;
  const bodyHeight = device.height + device.bezel * 2;
  const scale = Math.min(
    1,
    avail.width > 0 ? avail.width / bodyWidth : 1,
    avail.height > 0 ? avail.height / bodyHeight : 1,
  );

  return (
    <div className={cn('flex flex-col gap-3', className)}>
      <div ref={stageRef} className={cn('w-full', framed && 'flex justify-center')}>
        {framed ? (
          <DeviceFrame
            device={device}
            scale={scale}
            showSafeArea={showSafeArea}
            showPlatformChrome={showPlatformChrome}
            chrome={chrome}
          >
            <StageMedia
              mediaType={mediaType}
              src={src}
              poster={poster}
              title={title}
              framed
              refreshSrc={refreshSrc}
            />
            {overlay ? <div className="absolute inset-0">{overlay}</div> : null}
          </DeviceFrame>
        ) : (
          <StageMedia
            mediaType={mediaType}
            src={src}
            poster={poster}
            title={title}
            framed={false}
            refreshSrc={refreshSrc}
            maxHeight={maxHeight}
          />
        )}
      </div>

      <div className={cn('flex flex-wrap items-center gap-2', edgeToEdge && 'px-4 sm:px-0')}>
        <DropdownMenu
          ariaLabel={t('deviceMenu')}
          triggerIcon={<IconVideo className="size-4" />}
          triggerLabel={framed ? device.name : t('noDevice')}
          align="start"
          width="w-60"
        >
          {(close) => (
            <>
              <DropdownMenuGroup label={t('deviceMenu')}>
                <DropdownMenuRadioItem
                  selected={!framed}
                  onSelect={() => {
                    setDeviceId(NO_DEVICE);
                    close();
                  }}
                >
                  {t('noDevice')}
                </DropdownMenuRadioItem>
                {DEVICES.map((item) => (
                  <DropdownMenuRadioItem
                    key={item.id}
                    selected={framed && item.id === device.id}
                    onSelect={() => {
                      setDeviceId(item.id);
                      close();
                    }}
                  >
                    {item.name}
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuGroup>
              <DropdownMenuFooter>
                {framed
                  ? t('screenSpec', {
                      width: device.width,
                      height: device.height,
                      dpr: device.dpr,
                    })
                  : t('noDeviceHint')}
              </DropdownMenuFooter>
            </>
          )}
        </DropdownMenu>

        <Toggle
          label={t('safeArea')}
          pressed={showSafeArea}
          disabled={!framed}
          onToggle={() => setShowSafeArea((value) => !value)}
        />
        <Toggle
          label={t('platformChrome')}
          pressed={showPlatformChrome}
          disabled={!framed}
          onToggle={() => setShowPlatformChrome((value) => !value)}
        />

        {framed ? (
          <p className="tabular ml-auto text-[11px] text-muted">
            {t('scale', { percent: Math.round(scale * 100) })}
          </p>
        ) : null}
      </div>
    </div>
  );
}

function StageMedia({
  mediaType,
  src,
  poster,
  title,
  framed,
  refreshSrc,
  maxHeight,
}: {
  mediaType: 'image' | 'video';
  src?: string | null;
  poster?: string | null;
  title: string;
  framed: boolean;
  refreshSrc?: () => Promise<string | null>;
  /** Only meaningful for the unframed still image below — the framed case
   * already respects it via `DevicePreview`'s own `avail`/`scale`. */
  maxHeight?: number;
}) {
  if (mediaType === 'image') {
    if (framed) {
      return src ? (
        <StillLightboxTrigger src={src} title={title} imgClassName="size-full object-cover" />
      ) : (
        <div className="grid size-full place-items-center text-sm text-muted">{title}</div>
      );
    }
    return <CappedStill src={src} title={title} maxHeight={maxHeight} />;
  }

  if (framed) {
    return (
      <VideoPlayer
        src={src}
        poster={poster}
        title={title}
        aspectRatio={null}
        objectFit="cover"
        bare
        className="size-full"
        refreshSrc={refreshSrc}
      />
    );
  }

  return <VideoPlayer src={src} poster={poster} title={title} refreshSrc={refreshSrc} />;
}

function CappedStill({
  src,
  title,
  maxHeight,
}: {
  src?: string | null;
  title: string;
  maxHeight?: number;
}) {
  const measureRef = useRef<HTMLDivElement>(null);
  const avail = useAvailableStage(measureRef, maxHeight);
  const [ratio, setRatio] = useState(16 / 9);
  const stage = fitWithinReferenceCanvas({
    ratio,
    availWidth: avail.width,
    availHeight: avail.height,
  });
  const measured = avail.width > 0;

  return (
    <div ref={measureRef} className="flex w-full justify-center">
      <div
        className="relative overflow-hidden rounded-[var(--radius-md)] border border-border bg-black"
        style={
          measured
            ? { width: stage.width, height: stage.height }
            : referenceStageFallbackStyle(ratio)
        }
      >
        {src ? (
          <StillLightboxTrigger
            src={src}
            title={title}
            imgClassName="size-full object-contain"
            onLoad={(event) => {
              const image = event.currentTarget;
              if (image.naturalWidth > 0 && image.naturalHeight > 0) {
                setRatio(image.naturalWidth / image.naturalHeight);
              }
            }}
          />
        ) : (
          <div className="grid size-full place-items-center text-sm text-muted">{title}</div>
        )}
      </div>
    </div>
  );
}

/**
 * Image-only click-to-enlarge. Video stays on `VideoPlayer`; this trigger
 * is what studio success, `/jobs/{id}`, and `/work/{id}` share via
 * `DevicePreview` so each caller does not grow its own lightbox state.
 */
function StillLightboxTrigger({
  src,
  title,
  imgClassName,
  onLoad,
}: {
  src: string;
  title: string;
  imgClassName: string;
  onLoad?: (event: React.SyntheticEvent<HTMLImageElement>) => void;
}) {
  const t = useTranslations('media');
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        aria-label={t('lightboxTitle')}
        onClick={() => setOpen(true)}
        className="size-full cursor-zoom-in bg-transparent p-0 hover:opacity-90 focus-visible:outline-2"
      >
        {/* eslint-disable-next-line @next/next/no-img-element -- signed object URLs. */}
        <img src={src} alt={title} className={imgClassName} onLoad={onLoad} />
      </button>
      <MediaLightbox open={open} src={src} alt={title} onClose={() => setOpen(false)} />
    </>
  );
}

function Toggle({
  label,
  pressed,
  disabled,
  onToggle,
}: {
  label: string;
  pressed: boolean;
  disabled?: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      disabled={disabled}
      onClick={onToggle}
      className={cn(
        'inline-flex h-9 items-center gap-1.5 rounded-[var(--radius-sm)] border px-2.5 text-xs font-medium transition-colors',
        'focus-visible:outline-2 disabled:cursor-not-allowed disabled:opacity-50',
        pressed
          ? 'border-primary bg-primary/12 text-primary'
          : 'border-border bg-surface-soft text-muted hover:text-text',
      )}
    >
      <IconCheck className={cn('size-3.5', pressed ? 'opacity-100' : 'opacity-0')} />
      {label}
    </button>
  );
}

'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useRef, useState } from 'react';

import { DeviceFrame } from '@/components/media/device-frame';
import { VideoPlayer } from '@/components/media/video-player';
import {
  DropdownMenu,
  DropdownMenuFooter,
  DropdownMenuGroup,
  DropdownMenuRadioItem,
} from '@/components/ui/dropdown-menu';
import { IconCheck, IconVideo } from '@/components/ui/icons';
import { DEVICES, deviceById, type PlatformChrome } from '@/lib/devices';
import { cn } from '@/lib/cn';

/** Selection that shows the clip at its own size, with no phone around it. */
export const NO_DEVICE = 'none';

/**
 * The media stage with an optional phone around it.
 *
 * The device list includes "no device" as its first choice rather than sitting
 * behind a separate toggle: framing is one decision with one control, and a
 * 16:9 clip has no reason to start inside a phone.
 */
export function DevicePreview({
  src,
  poster,
  title,
  defaultDeviceId = NO_DEVICE,
  maxHeight = 560,
  edgeToEdge = false,
  chrome,
  overlay,
  className,
}: {
  src?: string | null;
  poster?: string | null;
  title: string;
  /** `NO_DEVICE`, or an id from the device catalogue. */
  defaultDeviceId?: string;
  /** Ceiling for the framed phone, in px, before the container width applies. */
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
}) {
  const t = useTranslations('devicePreview');

  const [deviceId, setDeviceId] = useState(defaultDeviceId);
  const [showSafeArea, setShowSafeArea] = useState(true);
  const [showPlatformChrome, setShowPlatformChrome] = useState(false);
  const [available, setAvailable] = useState(0);

  const stageRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = stageRef.current;
    if (!node) return;
    const observer = new ResizeObserver((entries) => {
      setAvailable(entries[0]?.contentRect.width ?? 0);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const framed = deviceId !== NO_DEVICE;
  const device = deviceById(deviceId);
  const bodyWidth = device.width + device.bezel * 2;
  const bodyHeight = device.height + device.bezel * 2;
  // A 430pt body does not fit a 390px viewport, and the stage is often
  // narrower still; the smaller of the two constraints wins, never above 1:1.
  const scale = Math.min(
    1,
    available > 0 ? available / bodyWidth : 1,
    maxHeight > 0 ? maxHeight / bodyHeight : 1,
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
            <VideoPlayer
              src={src}
              poster={poster}
              title={title}
              aspectRatio={null}
              objectFit="cover"
              bare
              className="size-full"
            />
            {overlay ? <div className="absolute inset-0">{overlay}</div> : null}
          </DeviceFrame>
        ) : (
          <VideoPlayer src={src} poster={poster} title={title} />
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

'use client';

import { useTranslations } from 'next-intl';

import { PLATFORM_CHROME, type DeviceSpec, type PlatformChrome } from '@/lib/devices';
import { cn } from '@/lib/cn';

/**
 * A phone body with a clipped screen, drawn at the device's own point size and
 * then scaled to whatever room the caller has.
 *
 * `transform: scale` rather than a proportional re-layout: a 430pt phone has to
 * be shown inside a 390px viewport, and only a uniform scale keeps the corner
 * radius, the cutout and the safe-area insets in the same relation to each
 * other that they have on the real device. A scaled element keeps its unscaled
 * box in the layout, so the caller-facing wrapper reserves the scaled size
 * explicitly.
 */
export function DeviceFrame({
  device,
  scale = 1,
  showSafeArea = false,
  showPlatformChrome = false,
  chrome = PLATFORM_CHROME,
  className,
  children,
}: {
  device: DeviceSpec;
  scale?: number;
  /** Tints the status-bar and home-indicator insets. */
  showSafeArea?: boolean;
  /** Tints where a short-video app puts its own controls. */
  showPlatformChrome?: boolean;
  /**
   * Reserved shares of the screen, defaulting to the catalogue's guidance.
   *
   * The short-form studio passes the selected profile's numbers instead: those
   * come from the config centre and are the ones the compliance check applies.
   */
  chrome?: PlatformChrome;
  className?: string;
  children: React.ReactNode;
}) {
  const t = useTranslations('devicePreview');

  const bodyWidth = device.width + device.bezel * 2;
  const bodyHeight = device.height + device.bezel * 2;

  return (
    <div
      className={cn('relative max-w-full shrink-0 [contain:layout]', className)}
      style={{ width: bodyWidth * scale, height: bodyHeight * scale }}
    >
      <div
        className="absolute left-0 top-0 origin-top-left"
        style={{ width: bodyWidth, height: bodyHeight, transform: `scale(${scale})` }}
      >
        <div
          className="size-full border border-border bg-surface-raised shadow-raised"
          style={{ borderRadius: device.radius + device.bezel, padding: device.bezel }}
        >
          <div
            className="relative size-full overflow-hidden bg-black"
            style={{ borderRadius: device.radius }}
          >
            <div className="absolute inset-0">{children}</div>

            <Cutout device={device} />

            {showSafeArea ? (
              <div aria-hidden="true" className="pointer-events-none absolute inset-0">
                <div
                  className="absolute inset-x-0 top-0 border-b border-dashed border-danger/60 bg-danger/15"
                  style={{ height: device.safeArea.top }}
                />
                {device.safeArea.bottom > 0 ? (
                  <div
                    className="absolute inset-x-0 bottom-0 border-t border-dashed border-danger/60 bg-danger/15"
                    style={{ height: device.safeArea.bottom }}
                  />
                ) : null}
              </div>
            ) : null}

            {showPlatformChrome ? (
              <div
                aria-hidden="true"
                className="pointer-events-none absolute inset-0 text-[10px] font-medium text-primary"
              >
                <Zone
                  label={t('chromeTop')}
                  className="inset-x-0 top-0 items-start justify-center pt-1"
                  style={{ height: `${chrome.top * 100}%` }}
                />
                <Zone
                  label={t('chromeRight')}
                  className="right-0 items-center justify-center"
                  style={{
                    width: `${chrome.right * 100}%`,
                    top: `${chrome.top * 100}%`,
                    bottom: `${chrome.bottom * 100}%`,
                  }}
                />
                <Zone
                  label={t('chromeBottom')}
                  className="inset-x-0 bottom-0 items-end justify-center pb-1"
                  style={{ height: `${chrome.bottom * 100}%` }}
                />
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

function Zone({
  label,
  className,
  style,
}: {
  label: string;
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <div
      className={cn(
        'absolute flex border border-dashed border-primary/60 bg-primary/15 text-center',
        className,
      )}
      style={style}
    >
      <span className="px-1">{label}</span>
    </div>
  );
}

function Cutout({ device }: { device: DeviceSpec }) {
  if (device.cutout === 'none') return null;

  const shared = 'pointer-events-none absolute bg-black';
  if (device.cutout === 'punch-hole') {
    return (
      <span
        aria-hidden="true"
        className={cn(shared, 'left-1/2 top-3 size-3 -translate-x-1/2 rounded-full')}
      />
    );
  }

  // The island floats below the top edge; the notch hangs from it.
  const isIsland = device.cutout === 'island';
  return (
    <span
      aria-hidden="true"
      className={cn(
        shared,
        'left-1/2 -translate-x-1/2 rounded-full',
        isIsland ? 'top-3 h-8 w-28' : 'top-0 h-7 w-40 rounded-t-none',
      )}
    />
  );
}

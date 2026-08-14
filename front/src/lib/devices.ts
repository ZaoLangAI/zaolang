/**
 * Phone catalogue for the framed preview.
 *
 * Every number here is a *display* parameter, not a measurement anyone should
 * build on: the frame exists so an author can see whether their subject and
 * captions survive a phone's cutouts and a platform's UI, and being a few
 * points off on a corner radius does not change that answer. Keeping them in
 * one table is what makes them cheap to correct when a new model ships.
 *
 * Sizes are CSS logical pixels (points), i.e. what `window.innerWidth` reports
 * on the device, not the panel's physical pixel count.
 */

export type DeviceCutout = 'none' | 'notch' | 'island' | 'punch-hole';

export interface DeviceSpec {
  id: string;
  /** Model name; a proper noun, so it is not translated. */
  name: string;
  width: number;
  height: number;
  /** Device pixel ratio, shown so the author can reason about export size. */
  dpr: number;
  /** Screen corner radius in points. */
  radius: number;
  /** Body thickness around the screen in points. */
  bezel: number;
  cutout: DeviceCutout;
  /** Vertical insets the OS reserves: status bar and home indicator. */
  safeArea: { top: number; bottom: number };
}

export const DEVICES: readonly DeviceSpec[] = [
  {
    id: 'iphone-se',
    name: 'iPhone SE',
    width: 375,
    height: 667,
    dpr: 2,
    radius: 6,
    bezel: 14,
    cutout: 'none',
    safeArea: { top: 20, bottom: 0 },
  },
  {
    id: 'iphone-17',
    name: 'iPhone 17',
    width: 402,
    height: 874,
    dpr: 3,
    radius: 55,
    bezel: 10,
    cutout: 'island',
    safeArea: { top: 62, bottom: 34 },
  },
  {
    id: 'iphone-15',
    name: 'iPhone 15',
    width: 393,
    height: 852,
    dpr: 3,
    radius: 48,
    bezel: 10,
    cutout: 'island',
    safeArea: { top: 59, bottom: 34 },
  },
  {
    id: 'iphone-15-pro-max',
    name: 'iPhone 15 Pro Max',
    width: 430,
    height: 932,
    dpr: 3,
    radius: 52,
    bezel: 10,
    cutout: 'island',
    safeArea: { top: 59, bottom: 34 },
  },
  {
    id: 'xiaomi-14',
    name: 'Xiaomi 14',
    width: 393,
    height: 873,
    dpr: 3,
    radius: 44,
    bezel: 9,
    cutout: 'punch-hole',
    safeArea: { top: 40, bottom: 24 },
  },
  {
    id: 'huawei-mate-60-pro',
    name: 'HUAWEI Mate 60 Pro',
    width: 420,
    height: 907,
    dpr: 3,
    radius: 50,
    bezel: 10,
    cutout: 'punch-hole',
    safeArea: { top: 44, bottom: 24 },
  },
  {
    id: 'galaxy-s24',
    name: 'Galaxy S24',
    width: 360,
    height: 780,
    dpr: 3,
    radius: 40,
    bezel: 9,
    cutout: 'punch-hole',
    safeArea: { top: 36, bottom: 24 },
  },
  {
    id: 'galaxy-s24-ultra',
    name: 'Galaxy S24 Ultra',
    width: 411,
    height: 891,
    dpr: 3.5,
    radius: 24,
    bezel: 9,
    cutout: 'punch-hole',
    safeArea: { top: 40, bottom: 24 },
  },
] as const;

export const DEFAULT_DEVICE_ID = 'iphone-17';

/** iPhone 17 logical screen; height ceiling for uncapped C-end players. */
export const REFERENCE_CANVAS = { width: 402, height: 874 } as const;

/**
 * Desktop portrait preview height. 874pt is one full phone and pins 9:16 to
 * the laptop viewport; this keeps a phone clip beside the work-page rail.
 */
export const PORTRAIT_STAGE_MAX_HEIGHT = 600;

/** Falls back to the default rather than throwing: the id can come from a URL. */
export function deviceById(id: string): DeviceSpec {
  return (
    DEVICES.find((device) => device.id === id) ??
    DEVICES.find((device) => device.id === DEFAULT_DEVICE_ID) ??
    DEVICES[0]!
  );
}

/** `16 / 9`, `16/9`, or a plain number. */
export function parseCssRatio(value: string | null | undefined): number | null {
  if (!value) return null;
  const parts = value.split('/').map((part) => Number(part.trim()));
  if (parts.length === 2 && parts[0]! > 0 && parts[1]! > 0) return parts[0]! / parts[1]!;
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric > 0 ? numeric : null;
}

/**
 * Fit a media box of `ratio` (width / height) into the caller’s column.
 *
 * Landscape and square follow the parent width so 16:9 fills the work-page
 * stage. Portrait stays phone-sized: width ≤ 402, and on a desktop column
 * height ≤ 600 so 9:16 cannot pin itself to the viewport.
 */
export function fitWithinReferenceCanvas({
  ratio,
  availWidth,
  availHeight,
}: {
  ratio: number;
  availWidth: number;
  availHeight: number;
}): { width: number; height: number } {
  const safeRatio = Number.isFinite(ratio) && ratio > 0 ? ratio : 16 / 9;
  const availW = availWidth > 0 ? availWidth : REFERENCE_CANVAS.width;
  const availH = availHeight > 0 ? availHeight : REFERENCE_CANVAS.height;
  const portrait = safeRatio < 1;
  const desktopColumn = availW > REFERENCE_CANVAS.width;
  const maxWidth = portrait ? Math.min(availW, REFERENCE_CANVAS.width) : availW;
  let maxHeight = Math.min(REFERENCE_CANVAS.height, availH);
  if (portrait && desktopColumn) {
    maxHeight = Math.min(maxHeight, PORTRAIT_STAGE_MAX_HEIGHT);
  }
  if (safeRatio > maxWidth / maxHeight) {
    return { width: maxWidth, height: maxWidth / safeRatio };
  }
  return { width: maxHeight * safeRatio, height: maxHeight };
}

/** First-paint CSS before the parent has been measured. */
export function referenceStageFallbackStyle(ratio: number): {
  width: string;
  maxWidth?: number;
  maxHeight: number;
  aspectRatio: string;
} {
  const safeRatio = Number.isFinite(ratio) && ratio > 0 ? ratio : 16 / 9;
  if (safeRatio < 1) {
    return {
      width: '100%',
      maxWidth: REFERENCE_CANVAS.width,
      maxHeight: PORTRAIT_STAGE_MAX_HEIGHT,
      aspectRatio: String(safeRatio),
    };
  }
  return {
    width: '100%',
    maxHeight: REFERENCE_CANVAS.height,
    aspectRatio: String(safeRatio),
  };
}

/**
 * Where a short-video platform's own chrome sits, as a share of the screen.
 *
 * Author-facing guidance, not a contract: it answers "will my caption end up
 * under the like button", which is the single most common reason a vertical
 * cut has to be redone. The backend's `shortform` profile carries the
 * authoritative numbers once a clip is checked for compliance.
 */
export interface PlatformChrome {
  top: number;
  right: number;
  bottom: number;
}

export const PLATFORM_CHROME: PlatformChrome = {
  top: 0.1,
  right: 0.18,
  bottom: 0.22,
};

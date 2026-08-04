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

export const DEFAULT_DEVICE_ID = 'iphone-15';

/** Falls back to the default rather than throwing: the id can come from a URL. */
export function deviceById(id: string): DeviceSpec {
  return DEVICES.find((device) => device.id === id) ?? DEVICES[1]!;
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

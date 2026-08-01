import { regionCurrency, type Locale, type Region } from '@/i18n/routing';

/**
 * Compact counts.
 *
 * Chinese groups by 万 rather than by thousand, which `Intl` handles natively
 * with `notation: 'compact'` — hand-rolling it would get 1.3万 wrong.
 */
export function formatCount(value: number, locale: Locale): string {
  return new Intl.NumberFormat(locale, {
    notation: value >= 10_000 ? 'compact' : 'standard',
    maximumFractionDigits: 1,
  }).format(value);
}

export function formatNumber(value: number, locale: Locale): string {
  return new Intl.NumberFormat(locale).format(value);
}

/** Money is priced by region, not by reading language. */
export function formatMoney(minorUnits: number, region: Region, locale: Locale): string {
  const currency = regionCurrency[region];
  const zeroDecimal = currency === 'JPY';
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency,
    minimumFractionDigits: zeroDecimal ? 0 : 2,
  }).format(zeroDecimal ? minorUnits : minorUnits / 100);
}

export function formatDate(value: string | Date, locale: Locale): string {
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }).format(new Date(value));
}

export function formatDateTime(value: string | Date, locale: Locale): string {
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(value),
  );
}

const RELATIVE_STEPS: Array<[Intl.RelativeTimeFormatUnit, number]> = [
  ['second', 60],
  ['minute', 60],
  ['hour', 24],
  ['day', 7],
  ['week', 4.35],
  ['month', 12],
  ['year', Number.POSITIVE_INFINITY],
];

export function formatRelative(value: string | Date, locale: Locale, now = new Date()): string {
  const formatter = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });
  let delta = (new Date(value).getTime() - now.getTime()) / 1000;

  for (const [unit, span] of RELATIVE_STEPS) {
    if (Math.abs(delta) < span) return formatter.format(Math.round(delta), unit);
    delta /= span;
  }
  return formatter.format(Math.round(delta), 'year');
}

/** `mm:ss`, matching the durations printed on the design's poster cards. */
export function formatDuration(seconds: number): string {
  const safe = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(safe / 60);
  return `${String(minutes).padStart(2, '0')}:${String(safe % 60).padStart(2, '0')}`;
}

export function formatBytes(bytes: number, locale: Locale): string {
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(value)} ${units[unit]}`;
}

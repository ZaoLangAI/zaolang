import { DISPLAY_TIME_ZONE, regionCurrency, type Locale, type Region } from '@/i18n/routing';

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

/**
 * API timestamps are UTC. A payload that omitted `Z` / an offset must still
 * be treated as UTC — `new Date('2026-09-02T05:35:00')` would otherwise
 * become 05:35 in the browser's local zone and look "already converted".
 */
export function parseInstant(value: string | Date): Date {
  if (value instanceof Date) return value;
  const trimmed = value.trim();
  if (/[zZ]$|[+-]\d{2}:?\d{2}$/.test(trimmed)) return new Date(trimmed);
  if (/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) return new Date(`${trimmed}T00:00:00Z`);
  return new Date(`${trimmed}Z`);
}

export function formatDate(value: string | Date, locale: Locale): string {
  return new Intl.DateTimeFormat(locale, {
    dateStyle: 'medium',
    timeZone: DISPLAY_TIME_ZONE,
  }).format(parseInstant(value));
}

export function formatDateTime(value: string | Date, locale: Locale): string {
  return new Intl.DateTimeFormat(locale, {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: DISPLAY_TIME_ZONE,
  }).format(parseInstant(value));
}

const LOCAL_DATE_TIME = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/;

/** `datetime-local` value with no offset — `YYYY-MM-DDTHH:mm` or with seconds. */
export function isLocalDateTime(value: string): boolean {
  return LOCAL_DATE_TIME.test(value);
}

/**
 * Interprets a `datetime-local` wall clock in `timeZone` and returns an
 * offset ISO string the API can compare against stored UTC timestamps.
 */
export function localDateTimeToIso(value: string, timeZone: string): string {
  const match = LOCAL_DATE_TIME.exec(value);
  if (!match) return value;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6] ?? '0');
  const utcGuess = Date.UTC(year, month - 1, day, hour, minute, second);
  const offsetMs = zoneOffsetMs(new Date(utcGuess), timeZone);
  const instant = new Date(utcGuess - offsetMs);
  const correctedOffset = zoneOffsetMs(instant, timeZone);
  return toOffsetIso(new Date(utcGuess - correctedOffset), correctedOffset);
}

function zoneOffsetMs(instant: Date, timeZone: string): number {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(instant);
  const num = (type: Intl.DateTimeFormatPartTypes) =>
    Number(parts.find((part) => part.type === type)?.value);
  const asZone = Date.UTC(
    num('year'),
    num('month') - 1,
    num('day'),
    num('hour'),
    num('minute'),
    num('second'),
  );
  return asZone - instant.getTime();
}

function toOffsetIso(instant: Date, offsetMs: number): string {
  const offsetMinutes = Math.round(offsetMs / 60_000);
  const sign = offsetMinutes >= 0 ? '+' : '-';
  const abs = Math.abs(offsetMinutes);
  const hours = String(Math.floor(abs / 60)).padStart(2, '0');
  const minutes = String(abs % 60).padStart(2, '0');
  const wall = new Date(instant.getTime() + offsetMs);
  const stamp = [
    String(wall.getUTCFullYear()),
    '-',
    String(wall.getUTCMonth() + 1).padStart(2, '0'),
    '-',
    String(wall.getUTCDate()).padStart(2, '0'),
    'T',
    String(wall.getUTCHours()).padStart(2, '0'),
    ':',
    String(wall.getUTCMinutes()).padStart(2, '0'),
    ':',
    String(wall.getUTCSeconds()).padStart(2, '0'),
  ].join('');
  return `${stamp}${sign}${hours}:${minutes}`;
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
  let delta = (parseInstant(value).getTime() - now.getTime()) / 1000;

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

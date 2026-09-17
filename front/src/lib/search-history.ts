const STORAGE_KEY = 'zaolang:search-history';

/** Recent searches shown in the top bar's dropdown; not tied to the account. */
const MAX_ENTRIES = 8;

function readRaw(): string[] {
  if (typeof window === 'undefined') return [];
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '[]') as unknown;
    return Array.isArray(parsed)
      ? parsed.filter((value): value is string => typeof value === 'string')
      : [];
  } catch {
    return [];
  }
}

function writeRaw(entries: string[]): string[] {
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
  }
  return entries;
}

export function readSearchHistory(): string[] {
  return readRaw();
}

/** Moves a repeated query back to the front instead of duplicating it. */
export function addSearchHistory(query: string): string[] {
  const trimmed = query.trim();
  if (!trimmed) return readRaw();
  const next = [trimmed, ...readRaw().filter((value) => value !== trimmed)].slice(0, MAX_ENTRIES);
  return writeRaw(next);
}

export function removeSearchHistory(query: string): string[] {
  return writeRaw(readRaw().filter((value) => value !== query));
}

export function clearSearchHistory(): string[] {
  return writeRaw([]);
}

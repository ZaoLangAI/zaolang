/**
 * Parses and formats token-count fields (context length, max output tokens)
 * that admins would otherwise have to type out in full, like `1000000`.
 *
 * Mirrors the shape of `micro-usd.ts`: parsing returns `null` for anything
 * that is not a recognisable count, so a typo becomes a validation error
 * rather than a silently wrong number.
 */

const SUFFIX_MULTIPLIERS: Record<string, number> = {
  k: 1_000,
  m: 1_000_000,
};

/**
 * Accepts a plain integer (`"128000"`), a comma-grouped integer
 * (`"128,000"`), or a `k`/`m` suffixed value (`"128k"`, `"1.5M"`). Returns
 * `null` for anything else, including negative numbers and multiple
 * suffixes.
 */
export function parseTokenCount(input: string): number | null {
  const trimmed = input.trim();
  if (!trimmed) return 0;

  const withoutCommas = trimmed.replace(/,/g, '');
  const match = /^(\d+(?:\.\d+)?)([kKmM]?)$/.exec(withoutCommas);
  if (!match) return null;

  const [, digits, suffix] = match;
  const multiplier = suffix ? (SUFFIX_MULTIPLIERS[suffix.toLowerCase()] ?? 1) : 1;
  const value = Number(digits) * multiplier;
  // A `k`/`m` suffix on a non-integer digit part (e.g. "1.23456k") can still
  // land on a fraction of a token; round rather than reject, since the
  // operator's intent (roughly "1.2K tokens") is clear.
  const rounded = Math.round(value);
  return Number.isSafeInteger(rounded) && rounded >= 0 ? rounded : null;
}

/**
 * Formats a token count back into an editable shorthand string: exact
 * millions/thousands collapse to `"1M"` / `"128K"`, everything else falls
 * back to the plain digits so no precision is silently lost.
 */
export function formatTokenCount(value: number): string {
  if (!value) return '';
  if (value % 1_000_000 === 0) return `${value / 1_000_000}M`;
  if (value % 1_000 === 0) return `${value / 1_000}K`;
  return String(value);
}

/** `asset_consistency` config helpers for the admin form
 * (`back/app/platform_config/schemas.py:AssetConsistencyConfig`). */

export const CONSISTENCY_KINDS = ['character', 'scene', 'prop'] as const;
export type ConsistencyKind = (typeof CONSISTENCY_KINDS)[number];

/** The `thresholds` key that covers every image type of a kind without its own. */
export const ANY_ENTRY_TYPE = '*';

export type ConsistencyThresholds = Record<string, Record<string, number>>;

/** Sets (or, for blank input, removes) a kind's default `"*"` threshold,
 * keeping its per-image-type ones and dropping a kind left empty. */
export function withDefaultThreshold(
  thresholds: ConsistencyThresholds,
  kind: ConsistencyKind,
  raw: string,
): ConsistencyThresholds {
  const own = { ...(thresholds[kind] ?? {}) };
  if (raw.trim() === '') delete own[ANY_ENTRY_TYPE];
  else own[ANY_ENTRY_TYPE] = Math.round(Number(raw));
  const next = { ...thresholds, [kind]: own };
  if (Object.keys(own).length === 0) delete next[kind];
  return next;
}

/** `kinds` in canonical order after toggling one. */
export function toggledKinds(kinds: readonly string[], kind: ConsistencyKind, on: boolean) {
  return CONSISTENCY_KINDS.filter((item) => (item === kind ? on : kinds.includes(item)));
}

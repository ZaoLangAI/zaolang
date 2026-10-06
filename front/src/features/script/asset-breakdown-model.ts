import type {
  QualityTier,
  ScriptBreakdown,
  ScriptBreakdownApplyItem,
  ScriptBreakdownItem,
} from '@/lib/api/types';

/**
 * The 剧本拆解 dialog's state (`asset-breakdown-dialog.tsx`): one row per
 * proposed card (`POST /v1/scripts/{id}:breakdown`), each with the author's
 * choice — 新建 / 关联已有 / 忽略 — and, for a link, the card. Pure so the
 * choices, the request and the quote lines are vitest-covered.
 */

export type BreakdownKind = ScriptBreakdownItem['kind'];
export type BreakdownAction = ScriptBreakdownApplyItem['action'];

export const BREAKDOWN_KINDS: readonly BreakdownKind[] = ['character', 'scene', 'prop'];

export interface BreakdownRow {
  /** `${kind}:${name}` — names are unique per kind in a proposal. */
  key: string;
  item: ScriptBreakdownItem;
  action: BreakdownAction;
  /** The card a `link` row points at. */
  cardId: string | null;
}

export interface BreakdownState {
  rows: BreakdownRow[];
}

export type BreakdownEvent =
  | { type: 'load'; breakdown: ScriptBreakdown; kinds: readonly BreakdownKind[] }
  | { type: 'action'; key: string; action: BreakdownAction }
  | { type: 'card'; key: string; cardId: string | null }
  /** A column's 全部新建 / 全部忽略. */
  | { type: 'column'; kind: BreakdownKind; action: 'create' | 'skip' };

export const EMPTY_BREAKDOWN: BreakdownState = { rows: [] };

export function rowKey(item: Pick<ScriptBreakdownItem, 'kind' | 'name'>): string {
  return `${item.kind}:${item.name}`;
}

/** A character name is unique per owner, so a same-named card can only be
 * linked (the apply would 422). */
export function createBlocked(item: ScriptBreakdownItem): boolean {
  return item.kind === 'character' && (item.matches?.length ?? 0) > 0;
}

function suggestedCard(item: ScriptBreakdownItem): string | null {
  return item.linked_card_id ?? item.matches?.[0]?.id ?? null;
}

/** Already linked or a same-named card → link it; else create. Kinds the
 * dialog was not opened for (a library page's import) are skipped. */
function initialRow(item: ScriptBreakdownItem, included: boolean): BreakdownRow {
  const cardId = suggestedCard(item);
  const action: BreakdownAction = !included ? 'skip' : cardId ? 'link' : 'create';
  return { key: rowKey(item), item, action, cardId };
}

export function breakdownReducer(state: BreakdownState, event: BreakdownEvent): BreakdownState {
  switch (event.type) {
    case 'load': {
      const { characters, scenes, props } = event.breakdown;
      return {
        rows: [...characters, ...scenes, ...props].map((item) =>
          initialRow(item, event.kinds.includes(item.kind)),
        ),
      };
    }
    case 'action':
      return {
        rows: state.rows.map((row) => {
          if (row.key !== event.key) return row;
          if (event.action === 'create' && createBlocked(row.item)) return row;
          return {
            ...row,
            action: event.action,
            cardId: event.action === 'link' ? (row.cardId ?? suggestedCard(row.item)) : row.cardId,
          };
        }),
      };
    case 'card':
      return {
        rows: state.rows.map((row) =>
          row.key === event.key ? { ...row, action: 'link', cardId: event.cardId } : row,
        ),
      };
    case 'column':
      return {
        rows: state.rows.map((row) =>
          row.item.kind !== event.kind || (event.action === 'create' && createBlocked(row.item))
            ? row
            : { ...row, action: event.action },
        ),
      };
  }
}

export function rowsOf(state: BreakdownState, kind: BreakdownKind): BreakdownRow[] {
  return state.rows.filter((row) => row.item.kind === kind);
}

/** A `link` row with no card picked yet — the apply would 422. */
export function incompleteRows(state: BreakdownState): BreakdownRow[] {
  return state.rows.filter((row) => row.action === 'link' && !row.cardId);
}

export function createCounts(state: BreakdownState): Record<BreakdownKind, number> {
  const counts: Record<BreakdownKind, number> = { character: 0, scene: 0, prop: 0 };
  for (const row of state.rows) if (row.action === 'create') counts[row.item.kind] += 1;
  return counts;
}

/** Nothing to write: every row skipped. */
export function nothingToApply(state: BreakdownState): boolean {
  return state.rows.every((row) => row.action === 'skip');
}

/** `…:breakdown-apply` items; skipped rows are left out (they write nothing). */
export function applyItems(state: BreakdownState): ScriptBreakdownApplyItem[] {
  return state.rows
    .filter((row) => row.action !== 'skip')
    .map(({ item, action, cardId }) => ({
      kind: item.kind,
      name: item.name,
      action,
      card_id: action === 'link' ? cardId : null,
      description: action === 'create' ? item.description.slice(0, 2000) : item.description,
      headings: item.headings ?? [],
      age_stage: item.kind === 'character' ? (item.age_stage ?? null) : null,
      period: item.kind === 'character' ? null : (item.period ?? null),
      lighting: item.kind === 'scene' ? (item.lighting ?? null) : null,
    }));
}

/** `quote:batch` lines for the first images — one single-image job per new
 * card, priced exactly as the apply prices them. */
export function quoteLines(counts: Record<BreakdownKind, number>, qualityTier: QualityTier) {
  return BREAKDOWN_KINDS.filter((kind) => counts[kind] > 0).map((kind) => ({
    operation: 'text_to_image' as const,
    quality_tier: qualityTier,
    duration_seconds: 0,
    asset_kind: kind,
    character_views: null,
    count: counts[kind],
  }));
}

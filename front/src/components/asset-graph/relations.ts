import type { AssetRelation } from '@/lib/api/types';

import type { CardKind } from '@/components/library/entry-actions';

/** Mirrors `CHARACTER_RELATIONS` / `SCENE_RELATIONS` (`back/app/models/enums.py`). */
export const RELATIONS_BY_KIND: Record<CardKind, AssetRelation[]> = {
  character: ['age', 'outfit', 'emotion', 'scene', 'period', 'edit', 'custom'],
  scene: ['lighting', 'weather', 'state', 'period', 'edit', 'custom'],
};

/** Stroke colour per relation — the `--relation-*` tokens (`globals.css`).
 * Scene axes reuse the nearest character hue so a legend never needs more
 * than seven colours. */
export const RELATION_COLOR: Record<AssetRelation, string> = {
  age: 'var(--relation-age)',
  outfit: 'var(--relation-outfit)',
  emotion: 'var(--relation-emotion)',
  scene: 'var(--relation-scene)',
  period: 'var(--relation-period)',
  lighting: 'var(--relation-age)',
  weather: 'var(--relation-scene)',
  state: 'var(--relation-emotion)',
  edit: 'var(--relation-edit)',
  custom: 'var(--relation-custom)',
};

/** `assetGraph.relation.*` message key. */
export function relationLabelKey(relation: AssetRelation): string {
  return `relation.${relation}`;
}

/** Mirrors `asset_graph.service.MAX_EDGE_LABEL_LEN` / `MAX_RELATIONS_PER_EDGE`. */
export const MAX_EDGE_LABEL_LENGTH = 40;
export const MAX_RELATIONS_PER_EDGE = 6;

import type { AssetRelation } from '@/lib/api/types';

import type { CardKind } from '@/components/library/entry-actions';

/** The relations an author can pick — `CHARACTER_RELATIONS` /
 * `SCENE_RELATIONS` (`back/app/models/enums.py`) minus `edit`, which only
 * links versions of one image (`versions.ts`) and is never drawn, and
 * `camera`, which only a multi-angle job writes. */
export const RELATIONS_BY_KIND: Record<CardKind, AssetRelation[]> = {
  character: ['age', 'outfit', 'emotion', 'scene', 'period', 'custom'],
  scene: ['lighting', 'weather', 'state', 'period', 'custom'],
};

/** Mirrors `VOICE_RELATIONS` (`back/app/models/enums.py`). */
export const VOICE_RELATIONS: AssetRelation[] = ['age', 'emotion', 'scene', 'params', 'custom'];

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
  // A voice derived with other TTS parameters (P7).
  params: 'var(--relation-period)',
  // The same subject from another camera pose (多机位, AC-2) — auto only.
  camera: 'var(--relation-scene)',
  custom: 'var(--relation-custom)',
};

/** `assetGraph.relation.*` message key. */
export function relationLabelKey(relation: AssetRelation): string {
  return `relation.${relation}`;
}

/** Mirrors `asset_graph.service.MAX_EDGE_LABEL_LEN` / `MAX_RELATIONS_PER_EDGE`. */
export const MAX_EDGE_LABEL_LENGTH = 40;
export const MAX_RELATIONS_PER_EDGE = 6;

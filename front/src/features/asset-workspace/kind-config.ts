import type { CardKind } from '@/components/library/entry-actions';
import type { AssetGraph, AssetVariant, CameraPose } from '@/lib/api/types';

import { pose } from './camera';

/** What a slot holds. `pose` slots are camera angles (多机位, AC-2). */
export type SlotKind = 'portrait' | 'sheet' | 'pose' | 'expressions' | 'master' | 'in_scene';

export interface SlotDef {
  id: string;
  kind: SlotKind;
  /** Counted by the completeness badge and offered by 补齐缺失. */
  required: boolean;
  pose?: CameraPose;
}

export interface KindConfig {
  api: 'characters' | 'scenes' | 'props';
  segment: 'looks' | 'variants';
  assetKind: 'character' | 'scene' | 'prop';
  targetKey: 'target_character_id' | 'target_scene_id' | 'target_prop_id';
  /** Slots of one look / variant, in board order. */
  slots: SlotDef[];
}

const poseSlot = (id: string, value: CameraPose, required = true): SlotDef => ({
  id,
  kind: 'pose',
  required,
  pose: value,
});

/** The standard set per card kind — the plan's slot table. A character's
 * turnaround matches `characters.fill.ORBIT_SLOT_AZIMUTH`. */
export const KIND_CONFIG: Record<CardKind, KindConfig> = {
  character: {
    api: 'characters',
    segment: 'looks',
    assetKind: 'character',
    targetKey: 'target_character_id',
    slots: [
      { id: 'portrait', kind: 'portrait', required: true },
      { id: 'sheet', kind: 'sheet', required: true },
      poseSlot('front_figure', pose(0), false),
      poseSlot('side', pose(90)),
      poseSlot('back', pose(180)),
      poseSlot('left', pose(270)),
      poseSlot('three_quarter', pose(45)),
      { id: 'expressions', kind: 'expressions', required: true },
      { id: 'in_scene', kind: 'in_scene', required: false },
    ],
  },
  scene: {
    api: 'scenes',
    segment: 'variants',
    assetKind: 'scene',
    targetKey: 'target_scene_id',
    slots: [
      { id: 'master', kind: 'master', required: true },
      poseSlot('reverse', pose(180)),
      poseSlot('right', pose(90)),
      poseSlot('left', pose(270)),
      poseSlot('overhead', pose(0, 60, 'wide')),
      poseSlot('detail', pose(0, 0, 'close'), false),
    ],
  },
  prop: {
    api: 'props',
    segment: 'variants',
    assetKind: 'prop',
    targetKey: 'target_prop_id',
    slots: [
      { id: 'master', kind: 'master', required: true },
      poseSlot('side', pose(90)),
      poseSlot('back', pose(180)),
      poseSlot('left', pose(270)),
      poseSlot('top', pose(0, 60)),
      poseSlot('detail', pose(0, 0, 'close'), false),
    ],
  },
};

/** The text every slot job of this card starts from: name, description and
 * (a non-default look's) own description — the same seed the library's
 * jump-outs used. */
export function basePrompt(graph: AssetGraph, variant: AssetVariant): string {
  return [graph.name, graph.description, variant.is_default ? null : variant.description]
    .map((part) => (part ?? '').trim().replace(/[。.]+$/, ''))
    .filter(Boolean)
    .join('。');
}

export function cardBase(kind: CardKind, cardId: string): string {
  return `/v1/${KIND_CONFIG[kind].api}/${cardId}`;
}

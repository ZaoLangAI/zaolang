import type { CardKind } from '@/components/library/entry-actions';
import type { AssetEntry, AssetGraphPendingJob, AssetVariant } from '@/lib/api/types';

import { entryPose, poseKey } from './camera';
import { KIND_CONFIG, type SlotDef } from './kind-config';

export type SlotStatus = 'missing' | 'pending' | 'candidate' | 'approved';

export interface SlotState {
  slot: SlotDef;
  status: SlotStatus;
  approved: AssetEntry | null;
  candidates: AssetEntry[];
}

/** Which entries of a look / variant fill `slot` (any status). The identity
 * portrait is card-wide — `allEntries` is every variant's. */
export function slotEntries(
  kind: CardKind,
  slot: SlotDef,
  variant: AssetVariant,
  allEntries: AssetEntry[],
): AssetEntry[] {
  const entries = variant.entries ?? [];
  switch (slot.kind) {
    case 'portrait':
      return allEntries.filter((e) => e.entry_type === 'identity_portrait');
    case 'sheet':
      return entries.filter((e) => e.entry_type === 'character_sheet');
    case 'expressions':
      return entries.filter((e) => e.entry_type === 'expression_sheet');
    case 'master':
      return entries.filter((e) => e.entry_type === 'master');
    case 'in_scene':
      return entries.filter((e) => e.entry_type === 'pose');
    case 'panorama':
      return entries.filter((e) => e.entry_type === 'panorama');
    case 'pose': {
      const wanted = slot.pose ? poseKey(slot.pose) : null;
      const type = kind === 'scene' ? 'shot' : 'view';
      return entries.filter((e) => {
        if (e.entry_type !== type) return false;
        const shown = entryPose(e);
        return shown !== null && wanted !== null && poseKey(shown) === wanted;
      });
    }
  }
}

/** A running job filing into this look that could produce `slot`: an orbit
 * job for a pose slot, a panorama job for the panorama, any other job for
 * the rest. */
function pendingFor(
  slot: SlotDef,
  variant: AssetVariant,
  pending: AssetGraphPendingJob[],
): boolean {
  return pending.some((job) => {
    const here = !job.target_variant_id || job.target_variant_id === variant.id;
    if (!here) return false;
    if (slot.kind === 'pose') return job.mode === 'orbit';
    if (slot.kind === 'panorama') return job.mode === 'panorama';
    return job.mode !== 'orbit' && job.mode !== 'panorama';
  });
}

export function slotStates(
  kind: CardKind,
  variant: AssetVariant,
  allEntries: AssetEntry[],
  pending: AssetGraphPendingJob[] = [],
): SlotState[] {
  return KIND_CONFIG[kind].slots
    .filter((slot) => slot.kind !== 'portrait' || variant.is_default)
    .map((slot) => {
      const matches = slotEntries(kind, slot, variant, allEntries);
      const approved = matches.find((e) => e.status === 'approved') ?? null;
      const candidates = matches.filter((e) => e.status === 'candidate');
      const status: SlotStatus = approved
        ? 'approved'
        : pendingFor(slot, variant, pending)
          ? 'pending'
          : candidates.length
            ? 'candidate'
            : 'missing';
      return { slot, status, approved, candidates };
    });
}

/** `{done, total}` over the required slots — the library card badge. */
export function completeness(states: SlotState[]): { done: number; total: number } {
  const required = states.filter((state) => state.slot.required);
  return {
    done: required.filter((state) => state.status === 'approved').length,
    total: required.length,
  };
}

/** The default look / variant's completeness, from a list payload's
 * variants (characters: `looks`). */
export function cardCompleteness(
  kind: CardKind,
  variants: AssetVariant[],
): { done: number; total: number } | null {
  const main = variants.find((v) => v.is_default) ?? variants[0];
  if (!main) return null;
  const all = variants.flatMap((v) => v.entries ?? []);
  return completeness(slotStates(kind, main, all));
}

/** The image a pose slot is drawn from (`…:orbit`): character — an approved
 * front single figure, else the sheet; scene / prop — the master. */
export function orbitSource(kind: CardKind, variant: AssetVariant): AssetEntry | null {
  const approved = (variant.entries ?? []).filter((e) => e.status === 'approved');
  if (kind === 'character') {
    const figure = approved.find((e) => {
      const shown = e.entry_type === 'view' ? entryPose(e) : null;
      return shown !== null && poseKey(shown) === '0|0|medium';
    });
    return figure ?? approved.find((e) => e.entry_type === 'character_sheet') ?? null;
  }
  return approved.find((e) => e.entry_type === 'master') ?? null;
}

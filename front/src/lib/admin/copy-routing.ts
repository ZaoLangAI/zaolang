import type { SkillTemplate } from '@/lib/api/admin-types';

type CopySkillTemplate = SkillTemplate & { asset_kind?: string | null };

/** Client-facing image/video kinds whose copy polish uses the `enhance` slot. */
const ENHANCE_REQUEST_KINDS = new Set([
  'character',
  'scene',
  'cover',
  'character_action',
  'transition_video',
  'cover_video',
]);

/** The slot the copy skill editor / debug-chat should bind for this agent. */
export function copyEditorSlot(profile: { default_for_asset_kind?: string | null }): string {
  const kind = profile.default_for_asset_kind ?? '';
  return ENHANCE_REQUEST_KINDS.has(kind) ? 'enhance' : 'suggest';
}

export function recommendedCopyTemplateKey(kind: string | null | undefined): string {
  if (kind === 'character') return 'copy-enhance-character';
  if (kind === 'scene') return 'copy-enhance-scene';
  if (kind === 'cover') return 'copy-enhance-cover';
  if (kind === 'copy') return 'copy-suggest';
  return '';
}

export function assetKindLabelKey(
  kind: string,
):
  | 'assetKindDefaultCharacter'
  | 'assetKindDefaultScene'
  | 'assetKindDefaultCover'
  | 'assetKindDefaultCopy' {
  if (kind === 'character') return 'assetKindDefaultCharacter';
  if (kind === 'scene') return 'assetKindDefaultScene';
  if (kind === 'cover') return 'assetKindDefaultCover';
  return 'assetKindDefaultCopy';
}

/** Slot-filtered templates, then narrowed to this agent's request bucket.
 *
 * A dedicated `character` / `scene` / `cover` / `copy` agent only sees the
 * starting prompt written for that bucket — filling must not silently load
 * the generic enhance draft or another kind's specialised draft. Video
 * kinds (and any other enhance bucket without a dedicated template) still
 * get the generic enhance fallback. */
export function templatesForCopyAgent(
  templates: CopySkillTemplate[],
  slot: string,
  kind: string | null | undefined,
): CopySkillTemplate[] {
  const onSlot = templates.filter((template) => !template.role || template.slot === slot);
  const matches = (() => {
    if (kind === 'copy') {
      return onSlot.filter((template) => template.asset_kind === 'copy');
    }
    if (kind) {
      const dedicated = onSlot.filter((template) => template.asset_kind === kind);
      if (dedicated.length > 0) return dedicated;
      return onSlot.filter((template) => template.asset_kind == null);
    }
    return onSlot.filter(
      (template) => template.asset_kind === 'copy' || template.asset_kind == null,
    );
  })();
  return matches.sort((left, right) => {
    const leftMatch = left.asset_kind === kind ? 0 : 1;
    const rightMatch = right.asset_kind === kind ? 0 : 1;
    if (leftMatch !== rightMatch) return leftMatch - rightMatch;
    return left.key.localeCompare(right.key);
  });
}

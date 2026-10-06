import type { CardKind } from '@/components/library/entry-actions';
import { api } from '@/lib/api/client';
import type { AssetVariant } from '@/lib/api/types';
import { uploadFile } from '@/lib/upload';

import { KIND_CONFIG } from './kind-config';

/** 从图片新建: file an uploaded image as the new card's first approved
 * image — a character's identity portrait, a scene's / prop's hero plate —
 * and say which 创作 slot to open next. */
export async function seedCardImage(
  kind: CardKind,
  cardId: string,
  variants: AssetVariant[],
  file: File,
): Promise<string> {
  const config = KIND_CONFIG[kind];
  const main = variants.find((v) => v.is_default) ?? variants[0];
  if (!main) throw new Error('card has no default variant');
  const asset = await uploadFile(file, 'generation_reference');
  await api.post(`/v1/${config.api}/${cardId}/${config.segment}/${main.id}/entries`, {
    asset_id: asset.id,
    entry_type: kind === 'character' ? 'identity_portrait' : 'master',
  });
  return kind === 'character' ? 'sheet' : firstPoseSlot(kind);
}

function firstPoseSlot(kind: CardKind): string {
  return KIND_CONFIG[kind].slots.find((slot) => slot.kind === 'pose')?.id ?? 'master';
}

export function workspaceHref(manageHref: string, slot: string): string {
  return `${manageHref}?slot=${encodeURIComponent(slot)}`;
}

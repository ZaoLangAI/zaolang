'use client';

import { AssetWorkspace } from '@/features/asset-workspace/asset-workspace';
import type { WorkspaceTab } from '@/features/asset-workspace/tabs';
import type { AssetGraph } from '@/lib/api/types';
import { characterImageStudioHref, characterManageHref } from '@/lib/characters';

/**
 * `/create/characters/[id]` body: the character workspace — 创作 board,
 * looks graph, voices (`AssetWorkspace`). Studio jump-outs return here.
 */
export function CharacterManagePage({
  initial,
  initialLookId,
  initialTab,
  initialSlotId,
  initialSkillId,
}: {
  initial: AssetGraph;
  /** `?look=`: the look to open on. */
  initialLookId?: string | null;
  initialTab?: WorkspaceTab | null;
  initialSlotId?: string | null;
  /** `?skillId=`: a plaza style skill for the 创作 slots. */
  initialSkillId?: string | null;
}) {
  const returnTo = characterManageHref(initial.card_id);
  return (
    <AssetWorkspace
      kind="character"
      initial={initial}
      initialTab={initialTab}
      initialVariantId={initialLookId}
      initialSlotId={initialSlotId}
      initialSkillId={initialSkillId}
      generateHref={(look) =>
        characterImageStudioHref({
          characterId: initial.card_id,
          name: initial.name,
          appearance: [initial.description, look.is_default ? null : look.description]
            .filter(Boolean)
            .join('。'),
          variantId: look.id,
          returnTo,
        })
      }
      portraitHref={characterImageStudioHref({
        characterId: initial.card_id,
        name: initial.name,
        appearance: initial.description,
        portrait: true,
        returnTo,
      })}
    />
  );
}

'use client';

import { AssetWorkspace } from '@/features/asset-workspace/asset-workspace';
import type { WorkspaceTab } from '@/features/asset-workspace/tabs';
import type { AssetGraph } from '@/lib/api/types';

/**
 * `/create/characters/[id]` body: the character workspace — 创作 board,
 * looks graph, voices (`AssetWorkspace`). A look's 生成 and 生成定妆照
 * open the 创作 tab on that slot; there is no image studio to jump out to.
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
  return (
    <AssetWorkspace
      kind="character"
      initial={initial}
      initialTab={initialTab}
      initialVariantId={initialLookId}
      initialSlotId={initialSlotId}
      initialSkillId={initialSkillId}
    />
  );
}

'use client';

import { AssetWorkspace } from '@/features/asset-workspace/asset-workspace';
import type { WorkspaceTab } from '@/features/asset-workspace/tabs';
import type { AssetGraph } from '@/lib/api/types';

/** `/create/scenes/[id]` body: the scene workspace — 创作 board and the
 * variants graph (`AssetWorkspace`). A variant's 生成 opens it on the 创作
 * tab; there is no image studio to jump out to. */
export function SceneManagePage({
  initial,
  initialVariantId,
  initialTab,
  initialSlotId,
  initialSkillId,
}: {
  initial: AssetGraph;
  /** `?look=`: the variant to open on. */
  initialVariantId?: string | null;
  initialTab?: WorkspaceTab | null;
  initialSlotId?: string | null;
  /** `?skillId=`: a plaza style skill for the 创作 slots. */
  initialSkillId?: string | null;
}) {
  return (
    <AssetWorkspace
      kind="scene"
      initial={initial}
      initialTab={initialTab}
      initialVariantId={initialVariantId}
      initialSlotId={initialSlotId}
      initialSkillId={initialSkillId}
    />
  );
}

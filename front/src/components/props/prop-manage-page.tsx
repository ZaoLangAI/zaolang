'use client';

import { AssetWorkspace } from '@/features/asset-workspace/asset-workspace';
import type { WorkspaceTab } from '@/features/asset-workspace/tabs';
import type { AssetGraph } from '@/lib/api/types';

/** `/create/props/[id]` body: the prop workspace — 创作 board and the
 * conditions graph (`AssetWorkspace`). No image-studio jump-out: a
 * condition's 生成 opens it on the 创作 tab. */
export function PropManagePage({
  initial,
  initialVariantId,
  initialTab,
  initialSlotId,
  initialSkillId,
}: {
  initial: AssetGraph;
  /** `?look=`: the condition to open on. */
  initialVariantId?: string | null;
  initialTab?: WorkspaceTab | null;
  initialSlotId?: string | null;
  /** `?skillId=`: a plaza style skill for the 创作 slots. */
  initialSkillId?: string | null;
}) {
  return (
    <AssetWorkspace
      kind="prop"
      initial={initial}
      initialTab={initialTab}
      initialVariantId={initialVariantId}
      initialSlotId={initialSlotId}
      initialSkillId={initialSkillId}
    />
  );
}

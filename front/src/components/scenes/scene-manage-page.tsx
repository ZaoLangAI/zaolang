'use client';

import { AssetWorkspace } from '@/features/asset-workspace/asset-workspace';
import type { WorkspaceTab } from '@/features/asset-workspace/tabs';
import type { AssetGraph } from '@/lib/api/types';
import { sceneImageStudioHref, sceneManageHref } from '@/lib/scenes';

/** `/create/scenes/[id]` body: the scene workspace — 创作 board and the
 * variants graph (`AssetWorkspace`). */
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
  const returnTo = sceneManageHref(initial.card_id);
  return (
    <AssetWorkspace
      kind="scene"
      initial={initial}
      initialTab={initialTab}
      initialVariantId={initialVariantId}
      initialSlotId={initialSlotId}
      initialSkillId={initialSkillId}
      generateHref={(variant) =>
        sceneImageStudioHref({
          sceneId: initial.card_id,
          name: initial.name,
          description: initial.description,
          variantId: variant.id,
          presets: variant.presets as { lighting?: string | null; weather?: string | null },
          returnTo,
        })
      }
    />
  );
}

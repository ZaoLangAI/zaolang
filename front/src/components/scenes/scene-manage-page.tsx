'use client';

import { AssetGraphWorkspace } from '@/components/asset-graph/asset-graph-workspace';
import type { AssetGraph } from '@/lib/api/types';
import { sceneImageStudioHref, sceneManageHref } from '@/lib/scenes';

/** `/create/scenes/[id]` body: the scene's variants and images as a
 * relation graph (`AssetGraphWorkspace`). */
export function SceneManagePage({
  initial,
  initialVariantId,
}: {
  initial: AssetGraph;
  /** `?look=`: the variant to open on. */
  initialVariantId?: string | null;
}) {
  const returnTo = sceneManageHref(initial.card_id);
  return (
    <AssetGraphWorkspace
      kind="scene"
      initial={initial}
      initialLookId={initialVariantId}
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

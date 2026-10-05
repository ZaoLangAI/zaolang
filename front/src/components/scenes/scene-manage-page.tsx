'use client';

import { useState } from 'react';

import { AssetVariantsPanel } from '@/components/library/asset-variants-panel';
import { Card } from '@/components/ui/primitives';
import type { Scene } from '@/lib/api/types';
import { sceneImageStudioHref, sceneManageHref } from '@/lib/scenes';

/**
 * `/create/scenes/[id]`: one scene's variants (变体) and the images filed
 * under each — the page that replaced the library's variants drawer.
 */
export function SceneManagePage({
  initial,
  initialVariantId,
}: {
  initial: Scene;
  /** `?look=`: the variant to open on. */
  initialVariantId?: string | null;
}) {
  const [scene, setScene] = useState(initial);
  const returnTo = sceneManageHref(scene.id);

  return (
    <div className="flex flex-col gap-6">
      {scene.description ? (
        <Card className="p-4">
          <p className="whitespace-pre-line text-sm text-muted">{scene.description}</p>
        </Card>
      ) : null}
      <AssetVariantsPanel
        kind="scene"
        card={scene}
        variants={scene.variants ?? []}
        anchorEntryId={scene.anchor_entry_id}
        initialVariantId={initialVariantId}
        onCardChange={setScene}
        generateHref={(variant) =>
          sceneImageStudioHref({
            sceneId: scene.id,
            name: scene.name,
            description: scene.description,
            variantId: variant.id,
            presets: variant.presets as { lighting?: string | null; weather?: string | null },
            returnTo,
          })
        }
      />
    </div>
  );
}

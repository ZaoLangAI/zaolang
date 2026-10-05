'use client';

import { AssetGraphWorkspace } from '@/components/asset-graph/asset-graph-workspace';
import type { AssetGraph } from '@/lib/api/types';
import { characterImageStudioHref, characterManageHref } from '@/lib/characters';

/**
 * `/create/characters/[id]` body: the character's looks and images as a
 * relation graph (`AssetGraphWorkspace`). Studio jump-outs return here.
 */
export function CharacterManagePage({
  initial,
  initialLookId,
}: {
  initial: AssetGraph;
  /** `?look=`: the look to open on. */
  initialLookId?: string | null;
}) {
  const returnTo = characterManageHref(initial.card_id);
  return (
    <AssetGraphWorkspace
      kind="character"
      initial={initial}
      initialLookId={initialLookId}
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

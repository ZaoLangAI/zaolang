'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { AssetVariantsPanel } from '@/components/library/asset-variants-panel';
import { Card } from '@/components/ui/primitives';
import type { Character } from '@/lib/api/types';
import { characterImageStudioHref, characterManageHref } from '@/lib/characters';

/**
 * `/create/characters/[id]`: one character's looks (造型) and the images
 * filed under each — the page that replaced the library's looks drawer.
 * Studio jump-outs return here (`returnTo`), so 生成到此处 lands back on the
 * same card instead of the library grid.
 */
export function CharacterManagePage({
  initial,
  initialLookId,
}: {
  initial: Character;
  /** `?look=`: the look to open on. */
  initialLookId?: string | null;
}) {
  const t = useTranslations('characters');
  const [character, setCharacter] = useState(initial);
  const returnTo = characterManageHref(character.id);

  return (
    <div className="flex flex-col gap-6">
      {character.description || character.voice_description ? (
        <Card className="flex flex-col gap-1.5 p-4">
          {character.description ? (
            <p className="whitespace-pre-line text-sm text-muted">{character.description}</p>
          ) : null}
          {character.voice_description ? (
            <p className="text-xs text-muted">
              {t('voiceLabel')}: {character.voice_description}
            </p>
          ) : null}
        </Card>
      ) : null}
      <AssetVariantsPanel
        kind="character"
        card={character}
        variants={character.looks ?? []}
        anchorEntryId={character.anchor_entry_id}
        initialVariantId={initialLookId}
        onCardChange={setCharacter}
        generateHref={(look) =>
          characterImageStudioHref({
            characterId: character.id,
            name: character.name,
            appearance: [character.description, look.is_default ? null : look.description]
              .filter(Boolean)
              .join('。'),
            variantId: look.id,
            returnTo,
          })
        }
        portraitHref={characterImageStudioHref({
          characterId: character.id,
          name: character.name,
          appearance: character.description,
          portrait: true,
          returnTo,
        })}
      />
    </div>
  );
}

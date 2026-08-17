'use client';

import Link from 'next/link';
import { useTranslations } from 'next-intl';

import {
  DropdownMenu,
  DropdownMenuFooter,
  DropdownMenuGroup,
  DropdownMenuRadioItem,
} from '@/components/ui/dropdown-menu';
import { IconImage, IconUser } from '@/components/ui/icons';
import type { Character, Scene } from '@/lib/api/types';
import { useResource } from '@/lib/use-resource';

type LinkKind = 'character' | 'scene';

/**
 * The "关联角色卡 / 关联场景卡" affordance next to a character chip or scene
 * heading: pick one of the creator's own `Character`/`Scene` assets, or clear
 * the link. Deliberately a picker over the *existing* library, not an
 * inline create form — creating one with a name, description and reference
 * uploads belongs to the full library page (`manageHref`), linked from the
 * menu's footer, matching the plan's "reuse a lightweight picker, not the
 * full library page" for picking, while keeping creation itself in one place.
 *
 * `createHref`, when set, adds a second footer link that jumps out to the
 * full image-creation studio (`/create/new?mode=image_creation&...`,
 * assembled by the caller in `script-document-view.tsx`) to generate a
 * fresh character/scene image — still not an inline create form, just a
 * deep link carrying enough context (and a `returnTo`) for that separate
 * page to come back here afterwards.
 */
export function ScriptLinkPicker({
  kind,
  refId,
  onChange,
  createHref,
}: {
  kind: LinkKind;
  refId: string | null;
  onChange: (refId: string | null) => void;
  createHref?: string;
}) {
  const t = useTranslations('scriptStudio');
  const path = kind === 'character' ? '/v1/characters' : '/v1/scenes';
  const resource = useResource<(Character | Scene)[]>(path);
  const items = resource.data ?? [];
  const linked = items.find((item) => item.id === refId) ?? null;
  const manageHref = kind === 'character' ? '/create/characters' : '/create/scenes';
  const label = kind === 'character' ? t('linkCharacter') : t('linkScene');
  const createLabel = kind === 'character' ? t('generateCharacterImage') : t('generateSceneImage');

  return (
    <DropdownMenu
      align="start"
      width="w-56"
      ariaLabel={label}
      triggerIcon={kind === 'character' ? <IconUser className="size-3.5" /> : <IconImage className="size-3.5" />}
      triggerLabel={linked ? `${linked.name} · ${linked.reference_assets?.length ?? 0}` : label}
    >
      {(close) => (
        <>
          <DropdownMenuGroup label={label}>
            {resource.status === 'loading' ? (
              <p className="px-2 py-1.5 text-xs text-muted">{t('linkLoading')}</p>
            ) : items.length === 0 ? (
              <p className="px-2 py-1.5 text-xs text-muted">{t('linkEmpty')}</p>
            ) : (
              items.map((item) => (
                <DropdownMenuRadioItem
                  key={item.id}
                  selected={item.id === refId}
                  onSelect={() => {
                    onChange(item.id === refId ? null : item.id);
                    close();
                  }}
                >
                  {item.name}
                </DropdownMenuRadioItem>
              ))
            )}
          </DropdownMenuGroup>
          <DropdownMenuFooter>
            <Link href={manageHref} className="hover:text-text" onClick={close}>
              {kind === 'character' ? t('manageCharacters') : t('manageScenes')}
            </Link>
            {createHref ? (
              <>
                <span aria-hidden="true">·</span>
                <Link href={createHref} className="hover:text-text" onClick={close}>
                  {createLabel}
                </Link>
              </>
            ) : null}
          </DropdownMenuFooter>
        </>
      )}
    </DropdownMenu>
  );
}

'use client';

import Link from 'next/link';
import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import {
  DropdownMenu,
  DropdownMenuFooter,
  DropdownMenuGroup,
  DropdownMenuRadioItem,
} from '@/components/ui/dropdown-menu';
import { IconImage, IconSticker, IconUser } from '@/components/ui/icons';
import type { Character, Prop, Scene } from '@/lib/api/types';
import { characterManageHref } from '@/lib/characters';
import { propManageHref } from '@/lib/props';
import { sceneManageHref } from '@/lib/scenes';
import { useResource } from '@/lib/use-resource';

type LinkKind = 'character' | 'scene' | 'prop';

const LIBRARY: Record<
  LinkKind,
  { path: string; manageHref: string; cardHref: (id: string, variantId?: string | null) => string }
> = {
  character: {
    path: '/v1/characters',
    manageHref: '/create/characters',
    cardHref: characterManageHref,
  },
  scene: { path: '/v1/scenes', manageHref: '/create/scenes', cardHref: sceneManageHref },
  prop: { path: '/v1/props', manageHref: '/create/props', cardHref: propManageHref },
};

/**
 * The "关联角色卡 / 关联场景卡 / 关联道具卡" affordance next to a character
 * chip, scene heading or script prop: pick one of the creator's own cards, or
 * clear the link. A prop has no variant pick (script props link the card's
 * default condition). Deliberately a picker over the *existing* library, not an
 * inline create form — creating one with a name, description and reference
 * uploads belongs to the full library page (`manageHref`), linked from the
 * menu's footer, matching the plan's "reuse a lightweight picker, not the
 * full library page" for picking, while keeping creation itself in one place.
 *
 * `onCreate`, when set and nothing is linked yet, adds 新建角色卡 / 新建场景卡
 * to the footer: the caller (`script-document-view.tsx`) creates the card
 * straight from the script's character / scene, links it via
 * `PATCH /v1/scripts/{episode}/links` and resolves with its id. Once a card
 * is linked the footer offers 去创作 — the card's workspace, where its
 * images are generated (there is no image studio to jump out to).
 */
export function ScriptLinkPicker({
  kind,
  refId,
  variantId = null,
  onChange,
  onCreate,
  refreshKey,
}: {
  kind: LinkKind;
  refId: string | null;
  /** The linked card's look (character) / variant (scene); null = default.
   * Unused for a prop. */
  variantId?: string | null;
  onChange: (refId: string | null, variantId?: string | null) => void;
  /** Creates and links a card from the script; resolves with its id. */
  onCreate?: () => Promise<string | null>;
  /** Bumped after a batch job writes a new card so the picker reloads. */
  refreshKey?: number;
}) {
  const t = useTranslations('scriptStudio');
  const resource = useResource<(Character | Scene | Prop)[]>(LIBRARY[kind].path);

  useEffect(() => {
    if (refreshKey) resource.refetch();
    // `refetch` is stable; keying on it would only retrigger the same bump.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);
  const items = resource.data ?? [];
  const linked = items.find((item) => item.id === refId) ?? null;
  const linkedVariants =
    (linked &&
      kind !== 'prop' &&
      ('looks' in linked ? linked.looks : 'variants' in linked ? linked.variants : null)) ||
    [];
  const linkedVariant = linkedVariants.find((variant) => variant.id === variantId) ?? null;
  const manageHref = LIBRARY[kind].manageHref;
  const label =
    kind === 'character' ? t('linkCharacter') : kind === 'scene' ? t('linkScene') : t('linkProp');
  const createLabel = kind === 'character' ? t('createCharacterCard') : t('createSceneCard');
  const [creating, setCreating] = useState(false);
  // The new card's id until the parent's link update lands in `refId`, so
  // 去创作 shows the moment the card exists.
  const [createdId, setCreatedId] = useState<string | null>(null);
  const cardId = refId ?? createdId;
  const workspaceHref = cardId ? LIBRARY[kind].cardHref(cardId, refId ? variantId : null) : null;

  const create = async () => {
    if (!onCreate || creating) return;
    setCreating(true);
    try {
      const id = await onCreate();
      if (id) {
        setCreatedId(id);
        resource.refetch();
      }
    } finally {
      setCreating(false);
    }
  };

  return (
    <DropdownMenu
      align="start"
      width="w-56"
      ariaLabel={label}
      triggerIcon={
        kind === 'character' ? (
          <IconUser className="size-3.5" />
        ) : kind === 'scene' ? (
          <IconImage className="size-3.5" />
        ) : (
          <IconSticker className="size-3.5" />
        )
      }
      triggerLabel={
        linked
          ? linkedVariant && !linkedVariant.is_default
            ? `${linked.name} · ${linkedVariant.name}`
            : `${linked.name} · ${linked.reference_assets?.length ?? 0}`
          : label
      }
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
          {linked && linkedVariants.length > 1 ? (
            <DropdownMenuGroup label={kind === 'character' ? t('linkLook') : t('linkSceneVariant')}>
              {linkedVariants.map((variant) => (
                <DropdownMenuRadioItem
                  key={variant.id}
                  selected={variant.id === variantId || (variant.is_default && !linkedVariant)}
                  onSelect={() => {
                    onChange(linked.id, variant.is_default ? null : variant.id);
                    close();
                  }}
                >
                  {variant.name}
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuGroup>
          ) : null}
          <DropdownMenuFooter>
            <Link href={manageHref} className="hover:text-text" onClick={close}>
              {kind === 'character'
                ? t('manageCharacters')
                : kind === 'scene'
                  ? t('manageScenes')
                  : t('manageProps')}
            </Link>
            {workspaceHref ? (
              <>
                <span aria-hidden="true">·</span>
                <Link href={workspaceHref} className="hover:text-text" onClick={close}>
                  {t('goCreate')}
                </Link>
              </>
            ) : onCreate ? (
              <>
                <span aria-hidden="true">·</span>
                <button
                  type="button"
                  className="hover:text-text disabled:cursor-wait disabled:opacity-60"
                  disabled={creating}
                  aria-busy={creating}
                  onClick={() => void create()}
                >
                  {creating ? t('creatingCard') : createLabel}
                </button>
              </>
            ) : null}
          </DropdownMenuFooter>
        </>
      )}
    </DropdownMenu>
  );
}

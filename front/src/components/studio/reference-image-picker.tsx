'use client';

import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import type { AssetVariant } from '@/lib/api/types';
import { cn } from '@/lib/cn';

export interface PickableReference {
  asset_id: string;
  url?: string | null;
  view?: string | null;
  label?: string | null;
  entry_type?: string | null;
}

/** One card's pick: a look/variant, exact images, or both. */
export interface ReferencePick {
  variantId?: string;
  assetIds?: string[];
}

/** Most images one character/scene may contribute (`asset_ids` max). */
const MAX_PICKED = 4;

/**
 * Which of one character's looks (or a scene's variants) a job should use,
 * and optionally exactly which of its images — e.g. only the 婚礼 outfit.
 * With no pick the card contributes its default subset (`defaultAssetIds`,
 * shown ticked); picking a look sends its `variant_id` and lets the backend
 * choose that look's default subset unless images are ticked too.
 */
export function ReferenceImagePicker({
  label,
  variants,
  defaultAssetIds,
  value,
  onChange,
}: {
  label: string;
  variants: AssetVariant[];
  defaultAssetIds: string[];
  value: ReferencePick | undefined;
  onChange: (next: ReferencePick | undefined) => void;
}) {
  const t = useTranslations('remixPage');
  const fallback = variants.find((v) => v.is_default) ?? variants[0];
  const shown = variants.find((v) => v.id === value?.variantId) ?? fallback;
  const entries = shown?.entries ?? [];
  const hasLooks = variants.length > 1;
  if (!hasLooks && entries.length <= 1) return null;

  const checkedIds = value?.assetIds ?? (value?.variantId ? [] : defaultAssetIds.filter(Boolean));
  const toggle = (assetId: string) => {
    const next = checkedIds.includes(assetId)
      ? checkedIds.filter((id) => id !== assetId)
      : [...checkedIds, assetId];
    if (next.length === 0) {
      // No images ticked: fall back to the look's own default subset.
      onChange(value?.variantId ? { variantId: value.variantId } : undefined);
      return;
    }
    onChange({ variantId: value?.variantId, assetIds: next });
  };

  return (
    <fieldset className="ml-6 flex min-w-0 flex-col gap-1.5">
      <legend className="mb-1 text-[11px] text-muted">{label}</legend>
      {hasLooks ? (
        <div className="flex flex-wrap gap-1.5">
          {variants.map((variant) => {
            const selected = variant.is_default
              ? !value?.variantId
              : value?.variantId === variant.id;
            return (
              <button
                key={variant.id}
                type="button"
                aria-pressed={selected}
                onClick={() => onChange(variant.is_default ? undefined : { variantId: variant.id })}
                className={cn(
                  'rounded-[var(--radius-sm)] border px-2 py-1 text-[11px] transition-colors',
                  selected
                    ? 'border-primary bg-primary/10 text-text'
                    : 'border-border text-muted hover:text-text',
                )}
              >
                {variant.name}
              </button>
            );
          })}
        </div>
      ) : null}
      {value?.variantId && !value.assetIds ? (
        <p className="text-[10px] text-muted">{t('referencePickLookDefault')}</p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {entries.map((entry) => {
          const checked = checkedIds.includes(entry.asset_id);
          const disabled = !checked && checkedIds.length >= MAX_PICKED;
          const caption = referenceCaption(entry, t);
          return (
            <label
              key={entry.id}
              title={caption}
              className={cn(
                'relative flex w-16 flex-col items-center gap-1 rounded-[var(--radius-sm)] border p-1 text-[10px] leading-tight',
                'focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-[var(--focus)]',
                checked ? 'border-primary bg-primary/10 text-text' : 'border-border text-muted',
                disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer',
              )}
            >
              <input
                type="checkbox"
                className="sr-only"
                checked={checked}
                disabled={disabled}
                onChange={() => toggle(entry.asset_id)}
              />
              <span className="relative size-12 overflow-hidden rounded-[var(--radius-sm)] bg-surface-soft">
                {entry.url ? (
                  <Image src={entry.url} alt="" fill sizes="48px" className="object-cover" />
                ) : null}
              </span>
              <span className="w-full truncate text-center">{caption}</span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

function referenceCaption(
  entry: PickableReference,
  t: ReturnType<typeof useTranslations<'remixPage'>>,
): string {
  const label = entry.label?.trim();
  if (label) return label;
  switch (entry.entry_type ?? entry.view) {
    case 'character_sheet':
    case 'front':
      return t('referenceViewFront');
    case 'master':
    case 'establishing':
      return t('referenceViewMaster');
    default:
      break;
  }
  if (entry.view === 'side') return t('referenceViewSide');
  if (entry.view === 'back') return t('referenceViewBack');
  return t('referenceViewOther');
}

/**
 * Per-character/scene picks for a job. No entry for an id means "default
 * subset" (nothing is sent).
 */
export function useReferencePicks() {
  const [picks, setPicks] = useState<Record<string, ReferencePick | undefined>>({});
  const set = (ownerId: string, pick: ReferencePick | undefined) =>
    setPicks((current) => ({ ...current, [ownerId]: pick }));
  /** `*_ref_selection` items for the owners still selected that were picked. */
  const selectionFor = (
    ownerIds: string[],
  ): { ownerId: string; variant_id: string | null; asset_ids: string[] | null }[] =>
    ownerIds.flatMap((id) => {
      const pick = picks[id];
      if (!pick || (!pick.variantId && !pick.assetIds?.length)) return [];
      return [
        {
          ownerId: id,
          variant_id: pick.variantId ?? null,
          asset_ids: pick.assetIds?.length ? pick.assetIds : null,
        },
      ];
    });
  return { picks, set, selectionFor };
}

'use client';

import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { cn } from '@/lib/cn';

export interface PickableReference {
  asset_id: string;
  url?: string | null;
  view?: string | null;
  label?: string | null;
}

/** Most images one character/scene may contribute (`asset_ids` max). */
const MAX_PICKED = 4;

/**
 * Thumbnails + checkboxes for exactly which of one character's (or scene's)
 * reference images a job should use — e.g. only the 婚礼 outfit's sheet.
 * `selected` starts as the backend's default subset; the caller only sends
 * a selection once the user has changed it.
 */
export function ReferenceImagePicker({
  label,
  assets,
  selected,
  onChange,
}: {
  label: string;
  assets: PickableReference[];
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  const t = useTranslations('remixPage');
  if (assets.length <= 1) return null;
  const toggle = (assetId: string) => {
    const next = selected.includes(assetId)
      ? selected.filter((id) => id !== assetId)
      : [...selected, assetId];
    // Keep at least one picked: an empty pick means "nothing", which the
    // backend would reject.
    if (next.length > 0) onChange(next);
  };
  return (
    <fieldset className="ml-6 flex min-w-0 flex-col gap-1.5">
      <legend className="mb-1 text-[11px] text-muted">{label}</legend>
      <div className="flex flex-wrap gap-2">
        {assets.map((asset) => {
          const checked = selected.includes(asset.asset_id);
          const disabled = !checked && selected.length >= MAX_PICKED;
          const caption = referenceCaption(asset, t);
          return (
            <label
              key={asset.asset_id}
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
                onChange={() => toggle(asset.asset_id)}
              />
              <span className="relative size-12 overflow-hidden rounded-[var(--radius-sm)] bg-surface-soft">
                {asset.url ? (
                  <Image src={asset.url} alt="" fill sizes="48px" className="object-cover" />
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
  asset: PickableReference,
  t: ReturnType<typeof useTranslations<'remixPage'>>,
): string {
  const label = asset.label?.trim();
  if (label) return label;
  switch (asset.view) {
    case 'front':
      return t('referenceViewFront');
    case 'side':
      return t('referenceViewSide');
    case 'back':
      return t('referenceViewBack');
    case 'establishing':
      return t('referenceViewMaster');
    default:
      return t('referenceViewOther');
  }
}

/**
 * Per-character/scene image picks for a job. `undefined` for an id means
 * "default subset" (nothing is sent); a list means the user picked.
 */
export function useReferencePicks() {
  const [picks, setPicks] = useState<Record<string, string[]>>({});
  const set = (ownerId: string, assetIds: string[]) =>
    setPicks((current) => ({ ...current, [ownerId]: assetIds }));
  /** `[{ownerId, asset_ids}]` for the owners still selected that were picked. */
  const selectionFor = (ownerIds: string[]): { ownerId: string; asset_ids: string[] }[] =>
    ownerIds.flatMap((id) => {
      const assetIds = picks[id];
      return assetIds?.length ? [{ ownerId: id, asset_ids: assetIds }] : [];
    });
  return { picks, set, selectionFor };
}

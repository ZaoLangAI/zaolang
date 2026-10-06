import type { AssetEntry, Prop } from '@/lib/api/types';

type PropReferenceAsset = NonNullable<Prop['reference_assets']>[number];

// Mirrors `asset_variants.service.MAX_DEFAULT_SCENE_REFERENCES` — a prop
// takes the scene-like default subset (AC-4).
const MAX_DEFAULT_PROP_REFERENCES = 2;

/** The card's own workspace (创作 board, conditions graph). */
export function propManageHref(propId: string, variantId?: string | null): string {
  const base = `/create/props/${encodeURIComponent(propId)}`;
  return variantId ? `${base}?look=${encodeURIComponent(variantId)}` : base;
}

/** The one image a prop card shows — its hero plate (the backend projects a
 * prop's `master` as view `hero`), else the first approved image. */
export function propHeroAsset(
  prop: Pick<Prop, 'reference_assets'>,
): PropReferenceAsset | undefined {
  return (
    prop.reference_assets?.find((asset) => asset.view === 'hero') ?? prop.reference_assets?.[0]
  );
}

function approved(entries: AssetEntry[] | undefined): AssetEntry[] {
  return (entries ?? []).filter((entry) => entry.status !== 'candidate' && entry.asset_id);
}

/**
 * What a job sends for this prop when nothing was picked — mirrors
 * `asset_variants.service.default_subset` without a viewpoint: the default
 * condition's hero plate(s), then its other approved images, else the
 * card's anchor, else anything approved; at most 2.
 */
export function defaultPropReferenceIds(
  prop: Pick<Prop, 'variants' | 'anchor_entry_id'>,
): string[] {
  const variants = prop.variants ?? [];
  const target = variants.find((variant) => variant.is_default) ?? variants[0];
  const entries = approved(target?.entries);
  let ordered = [
    ...entries.filter((entry) => entry.entry_type === 'master'),
    ...entries.filter((entry) => entry.entry_type !== 'master'),
  ];
  const all = variants.flatMap((variant) => approved(variant.entries));
  if (!ordered.length) {
    const anchor = all.find((entry) => entry.id === prop.anchor_entry_id);
    ordered = anchor ? [anchor] : all;
  }
  return [...new Set(ordered.map((entry) => entry.asset_id))].slice(0, MAX_DEFAULT_PROP_REFERENCES);
}

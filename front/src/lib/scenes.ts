import type { Scene } from '@/lib/api/types';

type SceneReferenceAsset = NonNullable<Scene['reference_assets']>[number];

/** The card's own management page (variants and their images). */
export function sceneManageHref(sceneId: string, variantId?: string | null): string {
  const base = `/create/scenes/${encodeURIComponent(sceneId)}`;
  return variantId ? `${base}?look=${encodeURIComponent(variantId)}` : base;
}

/** The one image a scene card shows — its master plate: an explicit
 * establishing tag, else the first unlabelled asset (labelled ones are
 * 黄昏/战损… variants), else the first asset. Mirrors the backend's
 * `scenes.service.master_entry`. Extra refs stay on the card strip. */
export function sceneHeroAsset(scene: Scene): SceneReferenceAsset | undefined {
  return (
    scene.reference_assets?.find((asset) => asset.view === 'establishing') ??
    scene.reference_assets?.find((asset) => !asset.label?.trim()) ??
    scene.reference_assets?.[0]
  );
}

/**
 * What a job sends for this scene when nothing was picked — mirrors
 * `scenes.service.default_reference_asset_ids`: the master plate plus the
 * next unlabelled shot. Labelled variants (黄昏/战损…) only go in when picked
 * (`scene_ref_selection`).
 */
export function defaultSceneReferenceIds(scene: Scene): string[] {
  const entries = (scene.reference_assets ?? []).filter((asset) => asset.asset_id);
  const master = sceneHeroAsset(scene);
  const ordered = [
    ...(master ? [master] : []),
    ...entries.filter((asset) => asset.asset_id !== master?.asset_id && !asset.label?.trim()),
  ];
  return (ordered.length ? ordered : entries).slice(0, 2).map((asset) => asset.asset_id);
}

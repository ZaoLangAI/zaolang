import type { Scene } from '@/lib/api/types';
import { STUDIO_PROMPT_MAX_LENGTH } from '@/lib/prompt-limits';

type SceneReferenceAsset = NonNullable<Scene['reference_assets']>[number];

const SCENE_LIBRARY_RETURN_TO = '/create/scenes';

/** Name + description for a library or script jump-out. No layout suffix —
 * the scene planner does not append one the way the character sheet does. */
export function sceneImagePrompt(input: { name: string; description?: string | null }): string {
  const name = input.name.trim();
  const description = input.description?.trim().replace(/[。．.]+$/, '') ?? '';
  const prompt = description ? `${name}。${description}` : name;
  return prompt.slice(0, STUDIO_PROMPT_MAX_LENGTH);
}

/** Deep link into `ImageGenerationStudio` for a scene-hero job. */
export function sceneImageStudioHref(input: {
  sceneId: string;
  name: string;
  description?: string | null;
  returnTo?: string;
  /** File the image under this variant (`target_variant_id`)… */
  variantId?: string;
  /** …and pre-select its lighting/weather presets. */
  presets?: { lighting?: string | null; weather?: string | null };
}): string {
  const params = new URLSearchParams({
    mode: 'image_creation',
    assetKind: 'scene',
    targetSceneId: input.sceneId,
    prompt: sceneImagePrompt({ name: input.name, description: input.description }),
    subjectNameHint: input.name.trim().slice(0, 60),
    returnTo: input.returnTo ?? SCENE_LIBRARY_RETURN_TO,
  });
  if (input.variantId) params.set('targetVariantId', input.variantId);
  if (input.presets?.lighting) params.set('sceneLighting', input.presets.lighting);
  if (input.presets?.weather) params.set('sceneWeather', input.presets.weather);
  return `/create/new?${params.toString()}`;
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

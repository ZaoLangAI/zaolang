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
}): string {
  const params = new URLSearchParams({
    mode: 'image_creation',
    assetKind: 'scene',
    targetSceneId: input.sceneId,
    prompt: sceneImagePrompt({ name: input.name, description: input.description }),
    subjectNameHint: input.name.trim().slice(0, 60),
    returnTo: input.returnTo ?? SCENE_LIBRARY_RETURN_TO,
  });
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

import {
  MAX_SCENE_VARIANTS,
  MIN_SCENE_VARIANTS,
  type ScenePresetCombo,
  type ScenePresets,
} from '@/features/image-assets/vocabulary';

type Axis = keyof ScenePresets;

/**
 * The `scene_variants` a group submit sends: one combo per picked value on
 * the varied axis, each carrying the fixed values of the other axes. `null`
 * until the group is complete enough to submit.
 */
export function sceneVariantCombos(
  presets: ScenePresets,
  groupAxis: Axis | null,
  groupValues: string[],
): ScenePresetCombo[] | null {
  if (!groupAxis || groupValues.length < MIN_SCENE_VARIANTS) return null;
  const fixed: ScenePresetCombo = {
    lighting: presets.lighting ?? null,
    weather: presets.weather ?? null,
    state: presets.state ?? null,
    period: presets.period ?? null,
  };
  return groupValues
    .slice(0, MAX_SCENE_VARIANTS)
    .map((value) => ({ ...fixed, [groupAxis]: value }) as ScenePresetCombo);
}

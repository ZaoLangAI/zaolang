import type { components } from '@/lib/api/schema';

type Params = components['schemas']['GenerationParams'];
type Combo = components['schemas']['ScenePresetCombo'];

/**
 * The image assets' closed preset vocabulary (workspace slots, scene matrix,
 * graph inspectors), keyed exhaustively over the
 * generated unions (backend source: `back/app/domain/image_assets/
 * vocabulary.py`): a preset the backend adds fails typecheck here until it
 * has a label. Labels are i18n keys under `remixPage.presets`.
 */
export type CharacterExpression = NonNullable<Params['character_expressions']>[number];
export type SceneLighting = NonNullable<Combo['lighting']>;
export type SceneWeather = NonNullable<Combo['weather']>;
export type SceneState = NonNullable<Combo['state']>;
export type ScenePeriod = NonNullable<Combo['period']>;
export type ScenePresetCombo = Combo;
export type AgeStage = NonNullable<components['schemas']['VariantPresets']['age_stage']>;
export type PropState = NonNullable<components['schemas']['VariantPresets']['prop_state']>;
export type CharacterRefSelection = NonNullable<Params['character_ref_selection']>[number];
export type SceneRefSelection = NonNullable<Params['scene_ref_selection']>[number];
export type PropRefSelection = NonNullable<Params['prop_ref_selection']>[number];

export const CHARACTER_EXPRESSIONS: Record<CharacterExpression, { labelKey: string }> = {
  neutral: { labelKey: 'expression.neutral' },
  smile: { labelKey: 'expression.smile' },
  laugh: { labelKey: 'expression.laugh' },
  smirk: { labelKey: 'expression.smirk' },
  restrained: { labelKey: 'expression.restrained' },
  breakdown: { labelKey: 'expression.breakdown' },
  anger: { labelKey: 'expression.anger' },
  shock: { labelKey: 'expression.shock' },
  fear: { labelKey: 'expression.fear' },
  sad: { labelKey: 'expression.sad' },
  shy: { labelKey: 'expression.shy' },
  cold_gaze: { labelKey: 'expression.cold_gaze' },
};

export const SCENE_LIGHTINGS: Record<SceneLighting, { labelKey: string }> = {
  dawn: { labelKey: 'lighting.dawn' },
  day: { labelKey: 'lighting.day' },
  dusk: { labelKey: 'lighting.dusk' },
  night_interior: { labelKey: 'lighting.night_interior' },
  night_exterior: { labelKey: 'lighting.night_exterior' },
  candle: { labelKey: 'lighting.candle' },
  neon: { labelKey: 'lighting.neon' },
  overcast: { labelKey: 'lighting.overcast' },
};

export const SCENE_WEATHERS: Record<SceneWeather, { labelKey: string }> = {
  clear: { labelKey: 'weather.clear' },
  rain: { labelKey: 'weather.rain' },
  snow: { labelKey: 'weather.snow' },
  fog: { labelKey: 'weather.fog' },
  sandstorm: { labelKey: 'weather.sandstorm' },
};

export const SCENE_STATES: Record<SceneState, { labelKey: string }> = {
  intact: { labelKey: 'state.intact' },
  messy: { labelKey: 'state.messy' },
  searched: { labelKey: 'state.searched' },
  damage_light: { labelKey: 'state.damage_light' },
  damage_medium: { labelKey: 'state.damage_medium' },
  damage_heavy: { labelKey: 'state.damage_heavy' },
  ruins: { labelKey: 'state.ruins' },
  festive: { labelKey: 'state.festive' },
};

export const SCENE_PERIODS: Record<ScenePeriod, { labelKey: string }> = {
  ancient: { labelKey: 'period.ancient' },
  republic: { labelKey: 'period.republic' },
  '1980s': { labelKey: 'period.1980s' },
  '1990s': { labelKey: 'period.1990s' },
  contemporary: { labelKey: 'period.contemporary' },
  near_future: { labelKey: 'period.near_future' },
};

/** A prop variant's condition (AC-4) — `vocabulary.PropState`. Labels are
 * keys under `props.state`, not `remixPage.presets`. */
export const PROP_STATES: Record<PropState, { labelKey: string }> = {
  new: { labelKey: 'state.new' },
  worn: { labelKey: 'state.worn' },
  damaged: { labelKey: 'state.damaged' },
  broken: { labelKey: 'state.broken' },
};

/** A prop variant's presets: its condition and period. */
export interface PropPresets {
  prop_state?: PropState | null;
  period?: ScenePeriod | null;
}

/** A character look's age stage (P2-6) — `vocabulary.AgeStage`. */
export const AGE_STAGES: Record<AgeStage, { labelKey: string }> = {
  child: { labelKey: 'ageStage.child' },
  teen: { labelKey: 'ageStage.teen' },
  youth: { labelKey: 'ageStage.youth' },
  adult: { labelKey: 'ageStage.adult' },
  middle_aged: { labelKey: 'ageStage.middle_aged' },
  elderly: { labelKey: 'ageStage.elderly' },
};

/** Mirrors `vocabulary.MAX_CHARACTER_EXPRESSIONS` / `MIN/MAX_SCENE_VARIANTS`. */
export const MAX_CHARACTER_EXPRESSIONS = 9;
export const MIN_SCENE_VARIANTS = 2;
export const MAX_SCENE_VARIANTS = 4;
export const MAX_OUTFIT_LABEL_LENGTH = 20;

/** Keys in declaration order — `Object.keys` typed to the union. */
export function keysOf<K extends string>(record: Record<K, unknown>): K[] {
  return Object.keys(record) as K[];
}

export function isSceneLighting(value: unknown): value is SceneLighting {
  return typeof value === 'string' && value in SCENE_LIGHTINGS;
}

export function isSceneWeather(value: unknown): value is SceneWeather {
  return typeof value === 'string' && value in SCENE_WEATHERS;
}

export function isSceneState(value: unknown): value is SceneState {
  return typeof value === 'string' && value in SCENE_STATES;
}

export function isScenePeriod(value: unknown): value is ScenePeriod {
  return typeof value === 'string' && value in SCENE_PERIODS;
}

/** The single-image scene presets a studio/job carries. */
export interface ScenePresets {
  lighting?: SceneLighting;
  weather?: SceneWeather;
  state?: SceneState;
  period?: ScenePeriod;
}

/** `GenerationParams` preset fields, ready to spread into a submit body. */
export type AssetPresetParams = Pick<
  Params,
  | 'character_expressions'
  | 'character_outfit_label'
  | 'character_ref_selection'
  | 'scene_ref_selection'
  | 'prop_ref_selection'
  | 'reference_emotion'
  | 'reference_shot_size'
  | 'reference_camera_side'
  | 'reference_camera_height'
  | 'scene_lighting'
  | 'scene_weather'
  | 'scene_state'
  | 'scene_period'
  | 'scene_variants'
  | 'target_variant_id'
> & {
  /** Defaulted (`false`) on the backend, so the generated type marks it
   * required; only a character portrait polish ever sends it. */
  character_portrait?: boolean;
};

export function scenePresetParams(presets: ScenePresets): AssetPresetParams {
  return {
    scene_lighting: presets.lighting ?? null,
    scene_weather: presets.weather ?? null,
    scene_state: presets.state ?? null,
    scene_period: presets.period ?? null,
  };
}

/** Shared editor engine ports. External editor types never cross this boundary. */

export const TICKS_PER_SECOND = 120_000;
export const JS_MAX_SAFE_INTEGER = Number.MAX_SAFE_INTEGER;
export const MAX_COMMANDS_PER_BATCH = 100;
export const MAX_ELEMENTS_PER_DOCUMENT = 5_000;
export const MAX_DOCUMENT_BYTES = 5 * 1024 * 1024;

/** MVP product cap: classic SceneExporter holds the full output in memory. */
export const EXPORT_MAX_DURATION_TICKS = 30 * TICKS_PER_SECOND;
export const EXPORT_MAX_PIXELS = 1920 * 1080;
export const EXPORT_MAX_ESTIMATED_BYTES = 80 * 1024 * 1024;

export type TrackKind = 'video' | 'audio' | 'caption' | 'overlay';
/** `sticker` is structurally identical to `clip` (same fields, same track kind) — see `insert_clip`'s `element_type`. */
export type ElementType = 'clip' | 'caption' | 'brand' | 'sticker';

/**
 * `blur` alone runs through the vendored WASM module's real `gaussian-blur`
 * shader when available (confirmed working by direct test — it's the only
 * shader actually registered in the pinned Rust pipeline); every other type
 * is always a plain Canvas2D `ctx.filter`, on both the WASM and fallback
 * paths, since no GPU pass exists for them.
 */
export type EffectType = 'blur' | 'brightness' | 'contrast' | 'saturate' | 'grayscale';

export interface ClipEffect {
  type: EffectType;
  /** `blur` reads `intensity` (0-100); brightness/contrast/saturate/grayscale read `amount` (percent, 100 = neutral). */
  params: Record<string, number>;
}

export type MaskShape = 'rect' | 'ellipse';

export interface ClipMask {
  shape: MaskShape;
  x_milli: number;
  y_milli: number;
  width_milli: number;
  height_milli: number;
  /** Feather radius as a fraction of canvas height, matching `BrandOverlay`'s milli-unit convention. */
  feather_millipercent: number;
}

export interface CanvasSpec {
  width: number;
  height: number;
  fps_num: number;
  fps_den: number;
}

/**
 * Coarse, hand-placed keyframes — not per-frame animation. Only `number`
 * channels exist so far (opacity, transform); `color`/`discrete` are named
 * in `kind` for forward compatibility with OpenCut's own documented channel
 * model but have no resolver yet, so nothing produces them today.
 */
export type AnimatableProperty =
  | 'opacity'
  | 'transform.x_milli'
  | 'transform.y_milli'
  | 'transform.scale_millipercent'
  | 'transform.rotation_millidegrees'
  /** Same millipercent range `set_clip_volume` accepts — an alternative, time-varying way to drive the same value. */
  | 'volume';

/** Shapes the curve used interpolating *away from* this point towards the next one — see `animation.ts`'s `resolveNumberAtTime`. A closed set, same reasoning as `AnimatableProperty`. */
export type EasingType = 'linear' | 'ease_in' | 'ease_out';

export interface AnimationPoint {
  at_ticks: number;
  value: number;
  /** Missing on points from before this field existed — treated as `'linear'` wherever read. */
  easing?: EasingType;
}

export interface AnimationChannel {
  kind: 'number';
  points: AnimationPoint[];
}

export interface ElementAnimations {
  channels: Partial<Record<AnimatableProperty, AnimationChannel>>;
}

export type TransitionType = 'crossfade' | 'dip_to_black';

export interface ClipTransition {
  type: TransitionType;
  duration_ticks: number;
}

export interface TimelineElement {
  id: string;
  type: ElementType;
  track_id: string;
  asset_id: string | null;
  start_ticks: number;
  duration_ticks: number;
  source_in_ticks: number;
  source_out_ticks: number;
  volume_millipercent: number;
  speed_millipercent: number;
  text: string | null;
  caption_language: string | null;
  effects: ClipEffect[];
  mask: ClipMask | null;
  animations: ElementAnimations;
  /** Set at this clip's own start/end edge; realized only when the adjacent clip on the same track actually overlaps it in time (via ordinary trim/move) — see `activeVideoLayer`. */
  transition_in: ClipTransition | null;
  transition_out: ClipTransition | null;
}

export interface TimelineTrack {
  id: string;
  kind: TrackKind;
  elements: TimelineElement[];
  /** Z-order for video tracks (higher = drawn on top); stable row order otherwise. */
  order: number;
  label: string | null;
  muted: boolean;
}

export interface BrandOverlay {
  asset_id: string;
  x_milli: number;
  y_milli: number;
  width_milli: number;
}

/** A timeline bookmark for navigation/annotation only — never drawn, never affects rendering. */
export interface Marker {
  id: string;
  at_ticks: number;
  label: string | null;
}

export interface CanonicalDocument {
  schema_version: 1;
  engine: 'zaolang-canonical';
  canvas: CanvasSpec;
  tracks: TimelineTrack[];
  brand_overlay: BrandOverlay | null;
  markers: Marker[];
}

export interface AssetBinding {
  asset_id: string;
  role: 'source' | 'caption' | 'brand' | 'font';
  duration_ticks: number | null;
}

export interface EditorDocumentEnvelope {
  schema_version: 1;
  document: CanonicalDocument;
  asset_bindings: AssetBinding[];
  duration_ticks: number;
  content_hash: string;
}

export type EditCommand =
  | {
      type: 'insert_clip';
      track_id: string;
      asset_id: string;
      at_ticks: number;
      duration_ticks: number;
      source_in_ticks?: number;
      element_id?: string;
      /** 'sticker' is structurally identical to the default 'clip' — same fields, same track kind, just a different visual role. */
      element_type?: 'clip' | 'sticker';
    }
  | { type: 'delete_elements'; element_ids: string[] }
  | { type: 'move_elements'; element_ids: string[]; delta_ticks: number; track_id?: string }
  | {
      type: 'trim_element';
      element_id: string;
      start_ticks: number;
      duration_ticks: number;
      source_in_ticks: number;
      source_out_ticks: number;
    }
  | { type: 'split_element'; element_id: string; at_ticks: number }
  | { type: 'set_clip_volume'; element_id: string; volume_millipercent: number }
  | { type: 'set_clip_speed'; element_id: string; speed_millipercent: number }
  | {
      type: 'insert_caption';
      track_id: string;
      at_ticks: number;
      duration_ticks: number;
      text: string;
      caption_language?: string;
      element_id?: string;
    }
  | {
      type: 'update_caption';
      element_id: string;
      text?: string;
      at_ticks?: number;
      duration_ticks?: number;
    }
  | { type: 'set_canvas'; width: number; height: number; fps_num?: number; fps_den?: number }
  | { type: 'set_brand_overlay'; overlay: BrandOverlay | null }
  | {
      type: 'add_track';
      kind: 'video' | 'audio';
      label?: string | null;
      order?: number;
      track_id?: string;
    }
  | { type: 'remove_track'; track_id: string }
  | { type: 'set_track_order'; track_id: string; order: number }
  | { type: 'set_track_muted'; track_id: string; muted: boolean }
  | { type: 'add_effect'; element_id: string; effect: ClipEffect }
  | { type: 'remove_effect'; element_id: string; effect_index: number }
  | {
      type: 'update_effect_params';
      element_id: string;
      effect_index: number;
      params: Record<string, number>;
    }
  | { type: 'set_clip_mask'; element_id: string; mask: ClipMask | null }
  | {
      type: 'set_keyframe';
      element_id: string;
      property: AnimatableProperty;
      at_ticks: number;
      value: number;
      /** Defaults to `'linear'` server-side when omitted. */
      easing?: EasingType;
    }
  | {
      type: 'delete_keyframe';
      element_id: string;
      property: AnimatableProperty;
      at_ticks: number;
    }
  | { type: 'clear_keyframes'; element_id: string; property: AnimatableProperty }
  | {
      type: 'set_transition';
      element_id: string;
      edge: 'in' | 'out';
      transition: ClipTransition | null;
    }
  | { type: 'add_marker'; at_ticks: number; label?: string | null; marker_id?: string }
  | { type: 'remove_marker'; marker_id: string }
  | { type: 'update_marker'; marker_id: string; at_ticks?: number; label?: string | null };

export interface EditCommandBatch {
  schema_version: 1;
  batch_id: string;
  expected_revision_id: string | null;
  commands: EditCommand[];
}

export interface ApplyResult {
  ok: boolean;
  envelope: EditorDocumentEnvelope;
  rolled_back: boolean;
  error?: string;
}

export interface ResolvedAsset {
  asset_id: string;
  mime_type: string;
  url: string;
  duration_ticks: number | null;
  width: number | null;
  height: number | null;
}

export interface VariantSpec {
  profile_key: string;
  width: number;
  height: number;
  fps_num: number;
  fps_den: number;
  format: 'mp4';
  caption_language: string | null;
  caption_mode: 'burned' | 'sidecar' | 'none';
  max_duration_ticks: number;
}

export interface CapabilityReport {
  ok: boolean;
  reasons: string[];
  estimated_bytes: number;
}

export interface ExportProgress {
  percent: number;
  stage: 'encoding' | 'uploading' | 'verifying';
  message: string;
  blob?: Blob;
}

export interface EditorEngine {
  load(document: EditorDocumentEnvelope, assets: ResolvedAsset[]): Promise<void>;
  apply(batch: EditCommandBatch): Promise<ApplyResult>;
  snapshot(): Promise<EditorDocumentEnvelope>;
  renderPreview(time: MediaTime): Promise<void>;
  dispose(): Promise<void>;
}

export interface RendererBackend {
  preflight(spec: VariantSpec): Promise<CapabilityReport>;
  export(
    spec: VariantSpec,
    document: CanonicalDocument,
    assets: ResolvedAsset[],
    signal: AbortSignal,
  ): AsyncIterable<ExportProgress>;
}

export interface CommandCodec {
  validate(input: unknown): EditCommandBatch;
  toClassic(batch: EditCommandBatch, context: MappingContext): unknown[];
}

export interface MappingContext {
  document: CanonicalDocument;
}

export type MediaTime = number;

export function assertSafeTicks(ticks: number, label: string): void {
  if (!Number.isInteger(ticks)) {
    throw new Error(`${label} must be an integer tick count`);
  }
  if (ticks < 0 || ticks > JS_MAX_SAFE_INTEGER) {
    throw new Error(`${label} is outside the safe integer tick range`);
  }
}

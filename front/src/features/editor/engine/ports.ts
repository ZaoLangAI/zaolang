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
export type ElementType = 'clip' | 'caption' | 'brand';

export interface CanvasSpec {
  width: number;
  height: number;
  fps_num: number;
  fps_den: number;
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
}

export interface TimelineTrack {
  id: string;
  kind: TrackKind;
  elements: TimelineElement[];
}

export interface BrandOverlay {
  asset_id: string;
  x_milli: number;
  y_milli: number;
  width_milli: number;
}

export interface CanonicalDocument {
  schema_version: 1;
  engine: 'zaolang-canonical';
  canvas: CanvasSpec;
  tracks: TimelineTrack[];
  brand_overlay: BrandOverlay | null;
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
  | { type: 'set_brand_overlay'; overlay: BrandOverlay | null };

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

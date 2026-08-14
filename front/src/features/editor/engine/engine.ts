import {
  applyBatch,
  cloneDocument,
  durationTicks,
  emptyDocument,
  validateBatch,
} from './canonical';
import type {
  ApplyResult,
  CanonicalDocument,
  EditCommandBatch,
  EditorDocumentEnvelope,
  EditorEngine,
  MediaTime,
  ResolvedAsset,
} from './ports';

export class CanonicalEditorEngine implements EditorEngine {
  private document: CanonicalDocument = emptyDocument();
  private assets: ResolvedAsset[] = [];
  private disposed = false;

  async load(envelope: EditorDocumentEnvelope, assets: ResolvedAsset[]): Promise<void> {
    this.assertLive();
    this.document = cloneDocument(envelope.document);
    this.assets = assets;
  }

  async apply(batch: EditCommandBatch): Promise<ApplyResult> {
    this.assertLive();
    const known = new Set(this.assets.map((asset) => asset.asset_id));
    try {
      const validated = validateBatch(batch);
      this.document = applyBatch(this.document, validated.commands, known);
      return { ok: true, envelope: this.snapshotSync(), rolled_back: false };
    } catch (error) {
      return {
        ok: false,
        envelope: this.snapshotSync(),
        rolled_back: true,
        error: error instanceof Error ? error.message : '命令批次已回滚',
      };
    }
  }

  async snapshot(): Promise<EditorDocumentEnvelope> {
    this.assertLive();
    return this.snapshotSync();
  }

  async renderPreview(_time: MediaTime): Promise<void> {
    this.assertLive();
  }

  async dispose(): Promise<void> {
    this.disposed = true;
    this.assets = [];
  }

  private snapshotSync(): EditorDocumentEnvelope {
    return {
      schema_version: 1,
      document: cloneDocument(this.document),
      asset_bindings: this.assets.map((asset) => ({
        asset_id: asset.asset_id,
        role: 'source',
        duration_ticks: asset.duration_ticks,
      })),
      duration_ticks: durationTicks(this.document),
      content_hash: '',
    };
  }

  private assertLive(): void {
    if (this.disposed) throw new Error('EditorEngine has been disposed');
  }
}

/** Two disposable engines must not share mutable state. */
export function createIndependentEngines(): [CanonicalEditorEngine, CanonicalEditorEngine] {
  return [new CanonicalEditorEngine(), new CanonicalEditorEngine()];
}

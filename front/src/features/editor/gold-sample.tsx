'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { ErrorNotice } from '@/components/ui/primitives';

import { applyBatch, emptyDocument } from './engine/canonical';
import { createIndependentEngines } from './engine/engine';
import { SequentialExportRunner } from './engine/export-runner';
import { TICKS_PER_SECOND, type EditorDocumentEnvelope } from './engine/ports';
import { EditorGate } from './gate';

function envelope(): EditorDocumentEnvelope {
  const document = emptyDocument();
  return {
    schema_version: 1,
    document,
    asset_bindings: [],
    duration_ticks: 0,
    content_hash: '',
  };
}

export function GoldSample() {
  const t = useTranslations('editor');
  const [enginesOk, setEnginesOk] = useState<boolean | null>(null);
  const [exportBytes, setExportBytes] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const [left, right] = createIndependentEngines();
      await left.load(envelope(), []);
      await right.load(envelope(), []);
      await left.apply({
        schema_version: 1,
        batch_id: 'gold-engines',
        expected_revision_id: null,
        commands: [
          {
            type: 'insert_caption',
            track_id: 'trk_caption',
            at_ticks: 0,
            duration_ticks: TICKS_PER_SECOND,
            text: 'left',
          },
        ],
      });
      const leftSnap = await left.snapshot();
      const rightSnap = await right.snapshot();
      await left.dispose();
      await right.dispose();
      if (cancelled) return;
      const leftHasCaption = leftSnap.document.tracks.some((track) => track.elements.length > 0);
      const rightEmpty = rightSnap.document.tracks.every((track) => track.elements.length === 0);
      setEnginesOk(leftHasCaption && rightEmpty);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const runExport = async () => {
    setRunning(true);
    setError(null);
    try {
      const runner = new SequentialExportRunner();
      const spec = {
        profile_key: 'gold',
        width: 640,
        height: 360,
        fps_num: 10,
        fps_den: 1,
        format: 'mp4' as const,
        caption_language: null,
        caption_mode: 'none' as const,
        max_duration_ticks: 10 * TICKS_PER_SECOND,
      };
      // No real media asset in this harness; exercises the real compositor +
      // encode path (background + caption layer) rather than a fake frame.
      const testDocument = applyBatch(
        emptyDocument(spec.width, spec.height),
        [
          {
            type: 'insert_caption',
            track_id: 'trk_caption',
            at_ticks: 0,
            duration_ticks: 10 * TICKS_PER_SECOND,
            text: 'ZaoLang gold sample',
          },
        ],
        new Set(),
      );
      let blob: Blob | undefined;
      for await (const progress of runner.export(
        spec,
        testDocument,
        [],
        new AbortController().signal,
      )) {
        blob = progress.blob ?? blob;
      }
      if (!blob) throw new Error('empty_export');
      setExportBytes(blob.size);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('commandFailed'));
    } finally {
      setRunning(false);
    }
  };

  return (
    <EditorGate>
      <div className="flex flex-col gap-4">
        <p data-testid="editor-engines" data-ok={enginesOk ? 'true' : 'false'}>
          {enginesOk ? t('goldEnginesOk') : t('goldEnginesPending')}
        </p>
        {error ? <ErrorNotice title={t('goldExportFailed')} detail={error} /> : null}
        {exportBytes != null ? (
          <p data-testid="editor-gold-sample" data-bytes={String(exportBytes)}>
            {t('goldExportOk', { bytes: exportBytes })}
          </p>
        ) : (
          <Button onClick={() => void runExport()} loading={running}>
            {t('goldExportStart')}
          </Button>
        )}
      </div>
    </EditorGate>
  );
}

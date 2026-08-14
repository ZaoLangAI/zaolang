'use client';

import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { Button } from '@/components/ui/button';
import { TextInput } from '@/components/ui/field';
import { EmptyState, ErrorNotice } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import { isApiError } from '@/lib/api/errors';
import type { ShortformProfile } from '@/lib/api/types';

import * as editorApi from './api';
import { CanvasPanel } from './canvas-panel';
import { EditPlanPanel } from './edit-plan-panel';
import { emptyDocument } from './engine/canonical';
import type { CanonicalDocument, EditCommand, ResolvedAsset, TimelineElement } from './engine/ports';
import { TICKS_PER_SECOND } from './engine/ports';
import { ExportPanel } from './export-panel';
import { EditorGate } from './gate';
import { Preview } from './preview';
import { useEditorUi } from './store';
import { Timeline } from './timeline';
import { useEditorLease } from './use-editor-lease';

export function DramaEditor({ cutId, draftId }: { cutId: string; draftId: string | null }) {
  const t = useTranslations('editor');
  const { notify } = useToast();
  const { lease, token } = useEditorLease(cutId);
  const readonly = useEditorUi((state) => state.readonly);
  const selectedIds = useEditorUi((state) => state.selectedIds);
  const playheadTicks = useEditorUi((state) => state.playheadTicks);
  const select = useEditorUi((state) => state.select);
  const [cut, setCut] = useState<editorApi.EpisodeCut | null>(null);
  const [document, setDocument] = useState<CanonicalDocument>(emptyDocument());
  const [profiles, setProfiles] = useState<ShortformProfile[]>([]);
  const [caption, setCaption] = useState('');
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const next = await editorApi.getCut(cutId);
    setCut(next);
    if (next.head?.document) setDocument(next.head.document);
  }, [cutId]);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      try {
        await reload();
      } catch (error) {
        if (!cancelled) setLoadError(isApiError(error) ? error.message : t('unavailable'));
      }
      const profiles = await editorApi.loadShortformProfiles();
      if (!cancelled) setProfiles(profiles.profiles);
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [reload, t]);

  const apply = async (commands: EditCommand[]) => {
    if (!cut || !lease || !token) return;
    setBusy(true);
    try {
      const revision = await editorApi.applyCommands(cut.id, {
        batchId: crypto.randomUUID(),
        expectedRevisionId: cut.head_revision_id,
        leaseId: lease.id,
        leaseToken: token,
        commands,
      });
      setDocument(revision.document);
      setCut({ ...cut, head_revision_id: revision.id, head: revision });
    } catch (error) {
      notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
    } finally {
      setBusy(false);
    }
  };

  const selected = selectedElement(document, selectedIds[0]);
  const disabled = readonly || busy || !token;
  const assetUrls = cut?.head?.asset_urls ?? {};
  // Keyed off the revision id rather than assetUrls itself: asset_urls only
  // ever changes together with the head revision, and the revision id is a
  // stable primitive the memo can depend on directly.
  const assets: ResolvedAsset[] = useMemo(
    () =>
      Object.entries(assetUrls).map(([assetId, url]) => ({
        asset_id: assetId,
        url,
        mime_type: 'video/mp4',
        duration_ticks: null,
        width: null,
        height: null,
      })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [cut?.head?.id],
  );

  if (loadError) {
    return <EmptyState title={t('unavailable')} description={loadError} />;
  }
  if (!cut) {
    return (
      <div className="grid min-h-[40vh] place-items-center">
        <Spinner label={t('loading')} />
      </div>
    );
  }

  return (
    <EditorGate>
      <div className="flex flex-col gap-6">
        {readonly ? <ErrorNotice title={t('readonlyLease')} detail={t('leaseLost')} /> : null}
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1.6fr)_minmax(20rem,1fr)]">
          <div className="flex flex-col gap-4">
            <Preview
              document={document}
              assets={assets}
              durationTicks={cut.head?.duration_ticks ?? 0}
              title={cut.name}
            />
            <p className="text-xs text-muted">
              {t('canvasLabel')} · {document.canvas.width}×{document.canvas.height} ·{' '}
              {t('durationLabel', {
                seconds: (Math.max(cut.head?.duration_ticks ?? 0, 0) / TICKS_PER_SECOND).toFixed(1),
              })}
            </p>
            <Timeline
              document={document}
              durationTicks={cut.head?.duration_ticks ?? TICKS_PER_SECOND}
              disabled={disabled}
              playheadLabel={t('playhead')}
              onSelect={(element) => select([element.id])}
              onCommand={(commands) => void apply(commands)}
            />
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="secondary"
                disabled={disabled || selectedIds.length === 0}
                onClick={() => void apply([{ type: 'delete_elements', element_ids: selectedIds }])}
              >
                {t('deleteSelected')}
              </Button>
              <Button
                size="sm"
                variant="secondary"
                disabled={disabled || !selected}
                onClick={() => {
                  if (!selected) return;
                  void apply([
                    { type: 'split_element', element_id: selected.id, at_ticks: playheadTicks },
                  ]);
                }}
              >
                {t('splitAtPlayhead')}
              </Button>
            </div>
            {selected?.type === 'clip' ? (
              <ClipAdjustControls
                key={selected.id}
                elementId={selected.id}
                initialVolume={selected.volume_millipercent}
                initialSpeed={selected.speed_millipercent}
                disabled={disabled}
                onCommit={(commands) => void apply(commands)}
              />
            ) : null}
            <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
              <TextInput
                label={t('captionText')}
                value={caption}
                onChange={(event) => setCaption(event.target.value)}
                disabled={disabled}
              />
              <Button
                disabled={disabled || !caption.trim()}
                onClick={() => {
                  void apply([
                    {
                      type: 'insert_caption',
                      track_id: 'trk_caption',
                      at_ticks: playheadTicks,
                      duration_ticks: TICKS_PER_SECOND * 2,
                      text: caption.trim(),
                    },
                  ]);
                  setCaption('');
                }}
              >
                {t('insertCaption')}
              </Button>
            </div>
            <CanvasPanel document={document} disabled={disabled} onApply={apply} />
          </div>
          <aside className="flex flex-col gap-4">
            <EditPlanPanel
              cutId={cut.id}
              leaseId={lease?.id ?? null}
              leaseToken={token}
              disabled={disabled}
              onApplied={() => void reload()}
            />
            <ExportPanel
              revisionId={cut.head_revision_id}
              document={document}
              assets={assets}
              durationTicks={cut.head?.duration_ticks ?? 0}
              draftId={draftId}
              disabled={disabled}
              profiles={profiles}
            />
          </aside>
        </div>
      </div>
    </EditorGate>
  );
}

function selectedElement(
  document: CanonicalDocument,
  id: string | undefined,
): TimelineElement | undefined {
  if (!id) return undefined;
  for (const track of document.tracks) {
    const found = track.elements.find((element) => element.id === id);
    if (found) return found;
  }
  return undefined;
}

/**
 * Local drag state seeded from the selected element and keyed by element id
 * in the parent so switching selection remounts (and re-seeds) it. Commits
 * to the server on release instead of on every drag tick.
 */
function ClipAdjustControls({
  elementId,
  initialVolume,
  initialSpeed,
  disabled,
  onCommit,
}: {
  elementId: string;
  initialVolume: number;
  initialSpeed: number;
  disabled: boolean;
  onCommit: (commands: EditCommand[]) => void;
}) {
  const t = useTranslations('editor');
  const [volume, setVolume] = useState(initialVolume);
  const [speed, setSpeed] = useState(initialSpeed);

  const commitVolume = () =>
    onCommit([{ type: 'set_clip_volume', element_id: elementId, volume_millipercent: volume }]);
  const commitSpeed = () =>
    onCommit([{ type: 'set_clip_speed', element_id: elementId, speed_millipercent: speed }]);

  return (
    <div className="flex flex-wrap items-center gap-4 text-xs text-muted">
      <label className="flex items-center gap-2">
        {t('volume')} {Math.round(volume / 1000)}%
        <input
          type="range"
          min={0}
          max={200_000}
          step={5_000}
          value={volume}
          disabled={disabled}
          onChange={(event) => setVolume(Number(event.target.value))}
          onPointerUp={commitVolume}
          onBlur={commitVolume}
        />
      </label>
      <label className="flex items-center gap-2">
        {t('speed')} {Math.round(speed / 1000)}%
        <input
          type="range"
          min={25_000}
          max={400_000}
          step={5_000}
          value={speed}
          disabled={disabled}
          onChange={(event) => setSpeed(Number(event.target.value))}
          onPointerUp={commitSpeed}
          onBlur={commitSpeed}
        />
      </label>
    </div>
  );
}

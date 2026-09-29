'use client';

import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { EmptyState } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import { isApiError } from '@/lib/api/errors';
import type { ShortformProfile } from '@/lib/api/types';
import { randomUuid } from '@/lib/random-id';
import { uploadFile } from '@/lib/upload';

import type { EditorActions } from './actions';
import * as editorApi from './api';
import {
  applyBatch,
  durationTicks as documentDuration,
  emptyDocument,
  newElementId,
  newMarkerId,
  newTrackId,
} from './engine/canonical';
import {
  TICKS_PER_SECOND,
  type CanonicalDocument,
  type EditCommand,
  type ResolvedAsset,
  type TimelineElement,
} from './engine/ports';
import { EditorGate } from './gate';
import { resolvedAssetFrom, useEditorUi } from './store';
import { StudioShell } from './studio/studio-shell';
import { elementIdsUnderTick, frameTicks } from './timeline/geometry';
import { useEditorLease } from './use-editor-lease';

/** Caps how many local undo/redo checkpoints are kept per session — unbounded growth is pointless since nobody undoes hundreds of steps back. */
const MAX_UNDO_CHECKPOINTS = 50;

interface QueuedBatch {
  batchId: string;
  commands: EditCommand[];
}

/**
 * Fills in every id the server would otherwise mint, so the local
 * (optimistic) document and the server's revision agree on element/track/
 * marker ids and a follow-up batch can already target them.
 */
function withPredictedIds(commands: EditCommand[]): EditCommand[] {
  return commands.map((command) => {
    switch (command.type) {
      case 'insert_clip':
      case 'insert_caption':
        return command.element_id ? command : { ...command, element_id: newElementId() };
      case 'add_track':
        return command.track_id ? command : { ...command, track_id: newTrackId() };
      case 'add_marker':
        return command.marker_id ? command : { ...command, marker_id: newMarkerId() };
      case 'split_element':
        return command.new_element_id ? command : { ...command, new_element_id: newElementId() };
      case 'duplicate_elements':
        return command.new_element_ids
          ? command
          : { ...command, new_element_ids: command.element_ids.map(() => newElementId()) };
      default:
        return command;
    }
  });
}

function findElement(
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

export function DramaEditor({ cutId, draftId }: { cutId: string; draftId: string | null }) {
  const t = useTranslations('editor');
  const { notify } = useToast();
  const { lease, token, heldByOther, reclaim, reclaiming } = useEditorLease(cutId);
  const readonly = useEditorUi((state) => state.readonly);
  const selectedIds = useEditorUi((state) => state.selectedIds);
  const playheadTicks = useEditorUi((state) => state.playheadTicks);
  const playing = useEditorUi((state) => state.playing);
  const clipboardIds = useEditorUi((state) => state.clipboardIds);
  const knownAssets = useEditorUi((state) => state.knownAssets);
  const select = useEditorUi((state) => state.select);
  const setPlayhead = useEditorUi((state) => state.setPlayhead);
  const setPlaying = useEditorUi((state) => state.setPlaying);
  const toggleSnapping = useEditorUi((state) => state.toggleSnapping);
  const setClipboard = useEditorUi((state) => state.setClipboard);
  const rememberAsset = useEditorUi((state) => state.rememberAsset);
  const [cut, setCut] = useState<editorApi.EpisodeCut | null>(null);
  const [document, setDocument] = useState<CanonicalDocument>(emptyDocument());
  const [profiles, setProfiles] = useState<ShortformProfile[]>([]);
  const [defaultProfile, setDefaultProfile] = useState<string | null>(null);
  const [caption, setCaption] = useState('');
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  // Bumped every time `document`/`cut` is set from a server response (initial
  // load, a confirmed command, a restore, or a post-conflict resync) — the
  // properties panel's per-clip controls key off this to remount and re-seed
  // their local draft state from the fresh props.
  const [syncNonce, setSyncNonce] = useState(0);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved'>('idle');
  const savedBadgeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // --- optimistic apply queue -------------------------------------------
  //
  // Every edit is applied to the local document first (same `applyBatch`
  // the server runs), so the UI reacts instantly; the batch then joins a
  // FIFO whose single in-flight request chains `expected_revision_id` onto
  // the previous confirmed revision. A rejected batch means local state has
  // diverged, so the queue is dropped and the cut is re-fetched.
  const documentRef = useRef(document);
  const headRef = useRef<string | null>(null);
  const queueRef = useRef<QueuedBatch[]>([]);
  const inflightRef = useRef(false);
  const cutRef = useRef<editorApi.EpisodeCut | null>(null);
  const leaseRef = useRef<{ id: string; token: string } | null>(null);
  useEffect(() => {
    leaseRef.current = lease && token ? { id: lease.id, token } : null;
  }, [lease, token]);

  const setLocalDocument = useCallback((next: CanonicalDocument) => {
    documentRef.current = next;
    setDocument(next);
  }, []);

  /**
   * Local undo/redo, session-only. `restoreRevision` always creates a *new*
   * immutable revision copying the target's content rather than literally
   * rewinding `head_revision_id` — so this stack stores the *logical*
   * checkpoint ids the user has visited, not a literal pointer into server
   * history. `stack[index]` is always "where we logically are"; undo/redo
   * only ever move `index`, never touch the stack — only a genuinely new
   * edit (or a manual History-panel restore) truncates any redo tail and
   * appends a fresh checkpoint.
   */
  const [checkpoints, setCheckpoints] = useState<{ stack: string[]; index: number }>({
    stack: [],
    index: -1,
  });
  const pushCheckpoint = useCallback((revisionId: string) => {
    setCheckpoints((current) => {
      const truncated = current.stack.slice(0, current.index + 1);
      truncated.push(revisionId);
      const trimmed =
        truncated.length > MAX_UNDO_CHECKPOINTS
          ? truncated.slice(truncated.length - MAX_UNDO_CHECKPOINTS)
          : truncated;
      return { stack: trimmed, index: trimmed.length - 1 };
    });
  }, []);
  const flashSaved = useCallback(() => {
    if (savedBadgeTimer.current) clearTimeout(savedBadgeTimer.current);
    setSaveStatus('saved');
    savedBadgeTimer.current = setTimeout(() => setSaveStatus('idle'), 2500);
  }, []);
  useEffect(
    () => () => {
      if (savedBadgeTimer.current) clearTimeout(savedBadgeTimer.current);
    },
    [],
  );

  const adoptRevision = useCallback(
    (next: editorApi.EpisodeCut) => {
      cutRef.current = next;
      headRef.current = next.head_revision_id;
      setCut(next);
      if (next.head?.document) setLocalDocument(next.head.document);
      setSyncNonce((n) => n + 1);
    },
    [setLocalDocument],
  );

  const reload = useCallback(async () => {
    const next = await editorApi.getCut(cutId);
    queueRef.current = [];
    adoptRevision(next);
    // A fresh load (initial mount) or a post-conflict resync both mean "the
    // server state we knew about is gone, start over" — reset the undo
    // stack to a single entry anchored at whatever the server says is head.
    setCheckpoints(
      next.head_revision_id
        ? { stack: [next.head_revision_id], index: 0 }
        : { stack: [], index: -1 },
    );
  }, [adoptRevision, cutId]);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      try {
        await reload();
      } catch (error) {
        if (!cancelled) setLoadError(isApiError(error) ? error.message : t('unavailable'));
      }
      const catalog = await editorApi.loadShortformProfiles();
      if (!cancelled) {
        setProfiles(catalog.profiles);
        setDefaultProfile(catalog.default_profile);
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [reload, t]);

  /**
   * A 409 REVISION_CONFLICT means our head no longer matches the server's
   * (another tab, a reclaimed lease, a retried request that landed twice).
   * Re-fetching realigns local state so the *next* command has a valid
   * `expected_revision_id`; the rejected edit itself was not applied and the
   * user is told to redo it against the refreshed document.
   */
  const recoverFromConflict = useCallback(
    async (error: unknown): Promise<boolean> => {
      if (!(isApiError(error) && error.code === 'REVISION_CONFLICT')) return false;
      try {
        await reload();
      } catch {
        // Best-effort resync — the conflict toast below still fires either way.
      }
      notify(t('revisionConflictRefreshed'), 'error');
      return true;
    },
    [notify, reload, t],
  );

  // `pump` re-enters itself once a batch settles; a ref keeps the recursion
  // pointed at the latest closure without the callback depending on itself.
  const pumpRef = useRef<() => void>(() => {});
  const pump = useCallback(() => {
    if (inflightRef.current) return;
    const item = queueRef.current.shift();
    const currentCut = cutRef.current;
    const currentLease = leaseRef.current;
    if (!item || !currentCut || !currentLease) {
      if (!item) setBusy(false);
      return;
    }
    inflightRef.current = true;
    setBusy(true);
    setSaveStatus('saving');
    void editorApi
      .applyCommands(currentCut.id, {
        batchId: item.batchId,
        expectedRevisionId: headRef.current,
        leaseId: currentLease.id,
        leaseToken: currentLease.token,
        commands: item.commands,
      })
      .then((revision) => {
        headRef.current = revision.id;
        const nextCut = {
          ...(cutRef.current ?? currentCut),
          head_revision_id: revision.id,
          head: revision,
        };
        cutRef.current = nextCut;
        setCut(nextCut);
        pushCheckpoint(revision.id);
        // Only let the server's document replace ours once nothing newer is
        // pending locally — otherwise we'd briefly roll back edits that are
        // still on their way.
        if (queueRef.current.length === 0) {
          setLocalDocument(revision.document);
          setSyncNonce((n) => n + 1);
          flashSaved();
        }
      })
      .catch(async (error: unknown) => {
        queueRef.current = [];
        setSaveStatus('idle');
        if (!(await recoverFromConflict(error))) {
          notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
          try {
            await reload();
          } catch {
            // The toast above already reports the failure.
          }
        }
      })
      .finally(() => {
        inflightRef.current = false;
        if (queueRef.current.length > 0) pumpRef.current();
        else setBusy(false);
      });
  }, [flashSaved, notify, pushCheckpoint, recoverFromConflict, reload, setLocalDocument, t]);
  useEffect(() => {
    pumpRef.current = pump;
  }, [pump]);

  const apply = useCallback(
    (rawCommands: EditCommand[]) => {
      if (!cutRef.current || !leaseRef.current || rawCommands.length === 0) return;
      const commands = withPredictedIds(rawCommands);
      let next: CanonicalDocument;
      try {
        next = applyBatch(documentRef.current, commands, new Set());
      } catch (error) {
        notify(error instanceof Error ? error.message : t('commandFailed'), 'error');
        return;
      }
      setLocalDocument(next);
      queueRef.current.push({ batchId: randomUuid(), commands });
      pump();
    },
    [notify, pump, setLocalDocument, t],
  );

  /** Resolves once every queued batch has been confirmed (or the queue was dropped). */
  const flush = useCallback(
    () =>
      new Promise<void>((resolve) => {
        const check = () => {
          if (!inflightRef.current && queueRef.current.length === 0) resolve();
          else setTimeout(check, 30);
        };
        check();
      }),
    [],
  );

  /** Shared restore mechanics — see `restore` (manual, from the History panel) vs `undo`/`redo` (checkpoint navigation). */
  const performRestore = async (revisionId: string): Promise<editorApi.CutRevision | null> => {
    await flush();
    const currentCut = cutRef.current;
    const currentLease = leaseRef.current;
    if (!currentCut || !currentLease) return null;
    setBusy(true);
    setSaveStatus('saving');
    try {
      const revision = await editorApi.restoreRevision(currentCut.id, {
        revisionId,
        expectedRevisionId: headRef.current,
        leaseId: currentLease.id,
        leaseToken: currentLease.token,
      });
      adoptRevision({ ...currentCut, head_revision_id: revision.id, head: revision });
      flashSaved();
      return revision;
    } catch (error) {
      setSaveStatus('idle');
      if (!(await recoverFromConflict(error))) {
        notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
      }
      return null;
    } finally {
      setBusy(false);
    }
  };

  const restore = async (revisionId: string) => {
    const revision = await performRestore(revisionId);
    if (revision) {
      pushCheckpoint(revision.id);
      notify(t('historyRestoreSuccess'), 'success');
    }
  };

  const canUndo = checkpoints.index > 0;
  const canRedo = checkpoints.index < checkpoints.stack.length - 1;

  const undo = async () => {
    if (!canUndo) return;
    const target = checkpoints.stack[checkpoints.index - 1];
    if (!target) return;
    const revision = await performRestore(target);
    if (revision) setCheckpoints((current) => ({ ...current, index: current.index - 1 }));
  };

  const redo = async () => {
    if (!canRedo) return;
    const target = checkpoints.stack[checkpoints.index + 1];
    if (!target) return;
    const revision = await performRestore(target);
    if (revision) setCheckpoints((current) => ({ ...current, index: current.index + 1 }));
  };

  const rename = async (name: string) => {
    const currentCut = cutRef.current;
    if (!currentCut || !name.trim() || name.trim() === currentCut.name) return;
    try {
      const next = await editorApi.renameCut(currentCut.id, name.trim());
      const merged = { ...currentCut, name: next.name };
      cutRef.current = merged;
      setCut(merged);
    } catch (error) {
      notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
    }
  };

  // Selection must never point at elements the (optimistic or server)
  // document no longer has.
  useEffect(() => {
    const present = new Set<string>();
    for (const track of document.tracks)
      for (const element of track.elements) present.add(element.id);
    if (selectedIds.some((id) => !present.has(id)))
      select(selectedIds.filter((id) => present.has(id)));
  }, [document, select, selectedIds]);

  const durationTicks = useMemo(() => documentDuration(document), [document]);
  const selected = findElement(document, selectedIds[0]);
  // Editing is gated on the lease alone — an in-flight save no longer
  // freezes the whole tree; `busy` only drives the header badge and the
  // server-side panels (history/AI plan) that must see a settled head.
  const disabled = readonly || !token;

  const revisionAssets = useMemo<ResolvedAsset[]>(() => {
    const urls = cut?.head?.asset_urls ?? {};
    const meta = cut?.head?.asset_meta ?? {};
    return Object.entries(urls).map(([assetId, url]) => {
      const info = meta[assetId];
      return {
        asset_id: assetId,
        url,
        mime_type: info?.mime_type ?? 'video/mp4',
        media_type: info?.media_type,
        duration_ticks: info?.duration_ticks ?? null,
        width: info?.width ?? null,
        height: info?.height ?? null,
      };
    });
  }, [cut?.head]);
  const assets = useMemo<ResolvedAsset[]>(() => {
    const byId = new Map(Object.values(knownAssets).map((asset) => [asset.asset_id, asset]));
    for (const asset of revisionAssets) byId.set(asset.asset_id, asset);
    return [...byId.values()];
  }, [knownAssets, revisionAssets]);

  // --- actions -------------------------------------------------------------

  const frame = frameTicks(document.canvas);
  const clampTick = (ticks: number) => Math.max(0, Math.min(durationTicks, Math.round(ticks)));
  const selectedElements = selectedIds
    .map((id) => findElement(document, id))
    .filter((item): item is TimelineElement => !!item);

  const trimTo = (element: TimelineElement, start: number, end: number): EditCommand => {
    if (element.type === 'caption') {
      return {
        type: 'update_caption',
        element_id: element.id,
        at_ticks: start,
        duration_ticks: end - start,
      };
    }
    const speed = Math.max(element.speed_millipercent, 1) / 100_000;
    const sourceIn = element.source_in_ticks + Math.round((start - element.start_ticks) * speed);
    return {
      type: 'trim_element',
      element_id: element.id,
      start_ticks: start,
      duration_ticks: end - start,
      source_in_ticks: sourceIn,
      source_out_ticks: sourceIn + (end - start),
    };
  };

  const actions: EditorActions = {
    canUndo,
    canRedo,
    canPaste: clipboardIds.some((id) => !!findElement(document, id)),
    undo: () => void undo(),
    redo: () => void redo(),
    splitAtPlayhead: () => {
      const targets =
        selectedIds.length > 0 ? selectedIds : elementIdsUnderTick(document, playheadTicks);
      const commands: EditCommand[] = [];
      for (const id of targets) {
        const element = findElement(document, id);
        if (!element) continue;
        if (
          playheadTicks > element.start_ticks &&
          playheadTicks < element.start_ticks + element.duration_ticks
        ) {
          commands.push({
            type: 'split_element',
            element_id: id,
            at_ticks: playheadTicks,
            new_element_id: newElementId(),
          });
        }
      }
      if (commands.length) apply(commands);
    },
    keepLeft: () => {
      const commands: EditCommand[] = [];
      const toDelete: string[] = [];
      for (const element of selectedElements) {
        const end = element.start_ticks + element.duration_ticks;
        if (playheadTicks <= element.start_ticks) toDelete.push(element.id);
        else if (playheadTicks < end)
          commands.push(trimTo(element, element.start_ticks, playheadTicks));
      }
      if (toDelete.length) commands.push({ type: 'delete_elements', element_ids: toDelete });
      if (commands.length) apply(commands);
    },
    keepRight: () => {
      const commands: EditCommand[] = [];
      const toDelete: string[] = [];
      for (const element of selectedElements) {
        const end = element.start_ticks + element.duration_ticks;
        if (playheadTicks >= end) toDelete.push(element.id);
        else if (playheadTicks > element.start_ticks)
          commands.push(trimTo(element, playheadTicks, end));
      }
      if (toDelete.length) commands.push({ type: 'delete_elements', element_ids: toDelete });
      if (commands.length) apply(commands);
    },
    duplicateSelected: () => {
      if (selectedIds.length === 0) return;
      const newIds = selectedIds.map(() => newElementId());
      apply([{ type: 'duplicate_elements', element_ids: selectedIds, new_element_ids: newIds }]);
      select(newIds);
    },
    copySelected: () => {
      if (selectedIds.length) setClipboard(selectedIds);
    },
    paste: () => {
      const sources = clipboardIds
        .map((id) => findElement(document, id))
        .filter((item): item is TimelineElement => !!item);
      if (sources.length === 0) return;
      const earliest = Math.min(...sources.map((element) => element.start_ticks));
      const newIds = sources.map(() => newElementId());
      apply([
        {
          type: 'duplicate_elements',
          element_ids: sources.map((element) => element.id),
          delta_ticks: playheadTicks - earliest,
          new_element_ids: newIds,
        },
      ]);
      select(newIds);
    },
    deleteSelected: () => {
      if (selectedIds.length) apply([{ type: 'delete_elements', element_ids: selectedIds }]);
    },
    selectAll: () =>
      select(document.tracks.flatMap((track) => track.elements.map((element) => element.id))),
    deselectAll: () => select([]),
    toggleMarkerAtPlayhead: () => {
      const existing = document.markers.find((marker) => marker.at_ticks === playheadTicks);
      if (existing) apply([{ type: 'remove_marker', marker_id: existing.id }]);
      else apply([{ type: 'add_marker', at_ticks: playheadTicks, marker_id: newMarkerId() }]);
    },
    alignSelectedToPlayhead: () => {
      if (selectedElements.length === 0) return;
      const earliest = Math.min(...selectedElements.map((element) => element.start_ticks));
      const delta = playheadTicks - earliest;
      if (delta !== 0)
        apply([{ type: 'move_elements', element_ids: selectedIds, delta_ticks: delta }]);
    },
    toggleSnapping,
    togglePlay: () => setPlaying(!playing),
    seekTo: (ticks) => setPlayhead(clampTick(ticks)),
    // Read the live playhead: key auto-repeat can fire several times per React commit.
    seekBy: (delta) => setPlayhead(clampTick(useEditorUi.getState().playheadTicks + delta)),
    stepFrames: (frames) =>
      setPlayhead(clampTick(useEditorUi.getState().playheadTicks + frames * frame)),
    goToStart: () => setPlayhead(0),
    goToEnd: () => setPlayhead(durationTicks),
    addTrack: (kind) => apply([{ type: 'add_track', kind, track_id: newTrackId() }]),
  };

  const dropFiles = async (files: File[], atTicks: number) => {
    let cursor = atTicks;
    for (const file of files) {
      try {
        const asset = await uploadFile(file, 'editor_source');
        const resolved = resolvedAssetFrom(asset);
        if (resolved) rememberAsset(resolved);
        const duration = resolved?.duration_ticks ?? 3 * TICKS_PER_SECOND;
        const kind = asset.media_type === 'audio' ? 'audio' : 'video';
        const trackId = documentRef.current.tracks.find((track) => track.kind === kind)?.id;
        if (!trackId) continue;
        apply([
          {
            type: 'insert_clip',
            track_id: trackId,
            asset_id: asset.id,
            at_ticks: cursor,
            duration_ticks: duration,
          },
        ]);
        cursor += duration;
      } catch (error) {
        notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
      }
    }
    if (files.length) notify(t('mediaUploadDone'), 'success');
  };

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
      <StudioShell
        cutName={cut.name}
        episodeId={cut.episode_id}
        saveStatus={saveStatus}
        readonly={readonly}
        heldByOther={heldByOther}
        reclaiming={reclaiming}
        onReclaim={() => void reclaim()}
        leaseExpiresAt={lease?.expires_at ?? null}
        document={document}
        assets={assets}
        durationTicks={durationTicks}
        disabled={disabled}
        serverBusy={busy}
        selected={selected}
        selectedIds={selectedIds}
        caption={caption}
        onCaptionChange={setCaption}
        onApply={apply}
        onRename={(name) => void rename(name)}
        actions={actions}
        revisionId={cut.head_revision_id}
        syncNonce={syncNonce}
        draftId={draftId}
        profiles={profiles}
        defaultProfile={defaultProfile}
        cutId={cut.id}
        leaseId={lease?.id ?? null}
        leaseToken={token}
        onPlanApplied={() => void reload()}
        onRestore={(revisionId) => void restore(revisionId)}
        onDropFiles={(files, atTicks) => void dropFiles(files, atTicks)}
      />
    </EditorGate>
  );
}
